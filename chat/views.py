from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json
import requests
import re
import torch
import logging
import time
from .models import Conversation, Message
from django.core.exceptions import ImproperlyConfigured
from django.views.decorators.http import require_GET
from transformers import AutoTokenizer, AutoModelForCausalLM

# 强制使用MPS加速（Apple Silicon专用）
if torch.backends.mps.is_available():
    # 内存优化配置
    torch.mps.set_per_process_memory_fraction(0.8)
    torch.mps.empty_cache()

# 日志记录器
logger = logging.getLogger(__name__)

# 初始化模型（M1优化版）
model_name = "Qwen/Qwen-1_8B-Chat"  # 或选择的其他模型
tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
# 使用内存映射技术加载模型
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="cpu" if torch.backends.mps.is_available() else "auto",          # 强制使用 MPS 加速
    torch_dtype=torch.float16,  # 半精度模式
    low_cpu_mem_usage=True,
    max_memory={"mps": "6GB"} if torch.backends.mps.is_available() else None, # 显存硬限制
    trust_remote_code=True
)

# 调用 Ollama API 发送消息
OLLAMA_API_BASE = 'http://192.168.1.14:11434/api'

# Django启动时自动检查（在views.py顶部）
def check_ollama_config():
    if not hasattr(settings, 'OLLAMA_API_BASE'):
        raise ImproperlyConfigured('OLLAMA_API_BASE未在settings中配置')

    if not settings.OLLAMA_API_BASE.startswith(('http://', 'https://')):
        raise ImproperlyConfigured('OLLAMA_API_BASE必须以http://或https://开头')

check_ollama_config()


def chat_view(request):
    return render(request, 'chat/chat.html')


@require_http_methods(["GET"])
def get_conversations(request):
    conversations = Conversation.objects.all().order_by('-created_at')
    data = [{
        'id': conv.id,
        'title': conv.title if conv.title else '新对话',
        'model': conv.model_name,
        'created_at': conv.created_at.strftime("%Y-%m-%d %H:%M")
    } for conv in conversations]
    return JsonResponse(data, safe=False)

@csrf_exempt
@require_http_methods(["POST"])
def new_conversation(request):
    try:
        data = json.loads(request.body)
        model_name = data.get('model', 'deepseek-r1:1.5b')

        # 模型验证
        if not model_name:
            return JsonResponse({'error': '模型不能为空'}, status=400)

        # 创建新的对话
        conv = Conversation.objects.create(
            title="新对话",
            model_name=model_name
        )

        return JsonResponse({'id': conv.id, 'title': conv.title})

    except json.JSONDecodeError:
        return JsonResponse({'error': '无效的JSON数据'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'服务器错误: {str(e)}'}, status=500)


@require_http_methods(["GET"])
def get_messages(request, conv_id):
    messages = Message.objects.filter(
        conversation_id=conv_id,
        is_deleted=False  # 确保只获取未删除的消息
    ).order_by('timestamp')  # 按时间排序

    if not messages:
        return JsonResponse({'error': '没有找到历史消息'}, status=404)

    # 返回消息的内容
    data = [{
        'id': msg.id,  # 包含消息的ID
        'role': msg.role,
        'content': msg.content,
        'time': msg.timestamp.strftime("%H:%M")  # 格式化时间
    } for msg in messages]

    return JsonResponse(data, safe=False)


@csrf_exempt
def chat(request):
    try:
        # 获取前端发送的数据
        data = json.loads(request.body)
        conv_id = data.get('conversation_id')
        user_message = data.get('messages', [])
        model_name = data.get('model')

        # 参数检查强化
        required_params = {
            'conversation_id': conv_id,
            'messages': user_message,
            'model': model_name
        }
        if not all(required_params.values()):
            missing = [k for k, v in required_params.items() if not v]
            return JsonResponse({'error': f'缺少必要参数: {", ".join(missing)}'}, status=400)

        # 获取对话对象（添加select_related优化查询）
        conv = get_object_or_404(Conversation.objects.select_related(), id=conv_id)

        # 保存用户消息（仅保存最新消息）
        try:
            last_user_msg = user_message[-1]['content']
        except (IndexError, KeyError):
            return JsonResponse({'error': '消息格式不正确'}, status=400)

        user_msg_obj = Message.objects.create(
            conversation=conv,
            content=last_user_msg,
            role='user'
        )

        # 获取AI回复（封装为独立函数）
        try:
            ai_response = get_ollama_response(model_name, user_message)
        except requests.RequestException as e:
            return JsonResponse({'error': f'模型请求失败: {str(e)}'}, status=500)

        # 保存AI回复
        ai_msg_obj = Message.objects.create(
            conversation=conv,
            content=ai_response,
            role='assistant'
        )

        # 标题生成条件判断优化
        message_count = Message.objects.filter(conversation=conv).count()

        # 移除<think>...</think>标签及其内容
        ai_response_clean = re.sub(r'<think>.*?</think>', '', ai_response, flags=re.DOTALL)

        if message_count == 2:  # 严格判断首次完整交互
            # 获取首轮对话内容
            first_interaction = f"用户：{user_msg_obj.content}\n助手：{ai_msg_obj.content}"

            # 获取处理内容
            second_interaction = f"用户：{user_msg_obj.content}\n助手：{ai_response_clean}"

            # # **添加调试日志**
            # print(f"First interaction (用户消息 + AI回复): {first_interaction}")
            # print(f"Second interaction (用户消息 + AI回复): {second_interaction}")

            # 增强版标题生成
            try:
                summary_title = generate_summary_with_qwen(second_interaction)
                # print(f"Generated title: {summary_title}")
                # 智能截断处理
                conv.title = (summary_title[:10] + '...') if len(summary_title) > 11 else summary_title
                conv.save(update_fields=['title'])
            except Exception as e:
                logger.error(f"标题生成失败: {str(e)}")
                conv.title = "新对话"
                conv.save(update_fields=['title'])

        # return JsonResponse({'response': ai_response})
        # 返回包含更新后的标题
        return JsonResponse({
            'response': ai_response,
            'conversation': {
                'id': conv.id,
                'title': conv.title,  # 返回最新的标题
                'model': conv.model_name,
                'created_at': conv.created_at.strftime("%Y-%m-%d %H:%M")
            }
        })


    except json.JSONDecodeError:
        return JsonResponse({'error': '无效的JSON数据'}, status=400)
    except Exception as e:
        logger.exception("服务器内部错误")
        return JsonResponse({'error': f'服务器错误: {str(e)}'}, status=500)


# 新增Ollama请求封装函数
def get_ollama_response(model_name, messages, timeout=600):
    """
    封装Ollama API请求，添加重试机制
    """
    payload = {
        'model': model_name,
        'messages': messages,
        'stream': False,
        'options': {
            'temperature': 0.7,
            'top_p': 0.9
        }
    }

    for attempt in range(3):
        try:
            response = requests.post(
                f'{settings.OLLAMA_API_BASE}/chat',
                json=payload,
                timeout=timeout
            )
            response.raise_for_status()
            return response.json().get('message', {}).get('content', '模型未响应')
        except requests.exceptions.Timeout:
            if attempt == 2:
                raise
            time.sleep(1)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 503:
                time.sleep(2)
                continue
            raise


@require_GET
@require_GET
def get_models(request):
    try:
        print(f"[DEBUG] 正在请求Ollama API: {settings.OLLAMA_API_BASE}/tags")
        response = requests.get(f'{settings.OLLAMA_API_BASE}/tags', timeout=5)
        response.raise_for_status()

        # 打印原始响应内容
        raw_data = response.json()
        print(f"[DEBUG] Ollama原始响应: {raw_data}")

        models = [model['name'] for model in raw_data.get('models', [])]
        print(f"[DEBUG] 解析后的模型列表: {models}")
        return JsonResponse(models, safe=False)
    except Exception as e:
        print(f"[ERROR] 获取模型列表失败: {str(e)}")
        return JsonResponse({'error': '模型服务不可用'}, status=503)



@csrf_exempt
@require_http_methods(["PATCH"])
def update_conversation_model(request, conv_id):
    try:
        data = json.loads(request.body)
        new_model = data['model']

        if not validate_model(new_model):
            return JsonResponse({'error': '指定模型不可用'}, status=400)

        conv = get_object_or_404(Conversation, id=conv_id)
        conv.model_name = new_model
        conv.save()
        return JsonResponse({'status': 'success'})

    except KeyError:
        return JsonResponse({'error': '缺少必要参数'}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({'error': '无效的JSON数据'}, status=400)


def validate_model(model_name):
    """验证模型是否存在于Ollama服务"""
    try:
        response = requests.post(
            f'{OLLAMA_API_BASE}/show',
            json={'name': model_name},  # 直接使用原始名称
            timeout=5
        )
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


@csrf_exempt
@require_http_methods(["DELETE"])
def delete_conversation(request, conv_id):
    try:
        # 获取对话对象
        conv = Conversation.objects.get(id=conv_id)

        # 删除对话，但不删除消息
        conv.delete()  # 只删除对话，不删除消息

        return JsonResponse({'status': 'success'})

    except Conversation.DoesNotExist:
        return JsonResponse({'error': '对话不存在'}, status=404)

# 获取对话的所有消息
@require_http_methods(["GET"])
def get_conversation_messages(request, conv_id):
    try:
        conversation = Conversation.objects.get(id=conv_id)
        messages = Message.objects.filter(conversation=conversation).order_by('timestamp')
        message_data = [{
            'role': msg.role,
            'content': msg.content,
            'time': msg.timestamp.strftime("%H:%M")
        } for msg in messages]

        return JsonResponse(message_data, safe=False)  # 设置 safe=False

    except Conversation.DoesNotExist:
        return JsonResponse({'error': '对话不存在'}, status=404)


@csrf_exempt
@require_http_methods(["PATCH"])
def update_conversation_title(request, conv_id):
    try:
        data = json.loads(request.body)
        new_title = data.get('title', None)

        if not new_title:
            return JsonResponse({'error': '标题不能为空'}, status=400)

        # 获取对话对象
        conv = get_object_or_404(Conversation, id=conv_id)

        # 更新对话标题
        conv.title = new_title
        conv.save()

        return JsonResponse({'status': 'success', 'title': conv.title})

    except Exception as e:
        return JsonResponse({'error': f'更新失败: {str(e)}'}, status=500)


def generate_summary_with_qwen(text):
    try:
        # Qwen专用提示模板
        prompt = (
            "<|im_start|>system\n"
            "你是一个对话标题生成器，依据以下对话内容生成一个简洁、准确的标题：\n"
            "1. 标题控制在10个字以内\n"
            "2. 准确反映对话主题\n"
            "3. 表明客观事实，简明扼要\n"
            "4. 不使用标点符号\n"
            "5. 避免冗余和无关信息，突出核心内容\n"
            f"对话内容：{text[:500]}<|im_end|>\n"
            "<|im_start|>assistant\n标题："
        )

        # 分词处理（适配Qwen格式）
        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            return_attention_mask=True,
            add_special_tokens=False  # 手动处理特殊token
        ).to(model.device)

        # 生成参数优化
        with torch.no_grad():
            outputs = model.generate(
                inputs.input_ids,
                max_new_tokens=4,  # 精确控制长度
                temperature=0.63,  # 平衡创意与稳定性
                top_p=0.85,
                repetition_penalty=1.2,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.im_end_id,  # Qwen专用结束符
                use_cache=True
            )

        # 精准提取响应内容
        full_response = tokenizer.decode(
            outputs[0],
            skip_special_tokens=False
        )

        # 使用Qwen专用分隔符解析
        title_part = full_response.split("<|im_start|>assistant\n")[-1]
        summary = title_part.split("<|im_end|>")[0].replace("标题：", "").strip()

        # 强化清洗规则
        summary = re.sub(
            r'[^\u4e00-\u9fa5]|(标题|内容|对话)',  # 过滤非汉字和关键词
            '',
            summary
        )[:10]  # 严格长度限制

        return summary

    except Exception as e:
        print(f"标题生成失败: {str(e)}")
        return "新对话"

















