class ChatApplication {
  constructor() {
    this.currentConversationId = null;
    this.currentModel = 'deepseek-r1:1.5b'; // 默认模型
    this.isProcessing = false;
    this.init();
    // this.loadChatHistory = this.loadChatHistory.bind(this);
  }

  init() {
    this.cacheElements();
    this.registerEventListeners();
    this.initializeApp();
  }

  cacheElements() {
    this.elements = {
      newChatBtn: document.getElementById('newChatBtn'),
      modelSelector: document.getElementById('modelSelector'),
      conversationList: document.getElementById('conversationList'),
      chatMessages: document.getElementById('chatMessages'),
      messageInput: document.getElementById('messageInput'),
      sendBtn: document.getElementById('sendBtn'),
      loadingOverlay: document.getElementById('loadingOverlay'),
      loadingIndicator: document.getElementById('loadingIndicator')
    };
  }

  registerEventListeners() {
    // 监听发送按钮点击事件
    this.elements.sendBtn.addEventListener('click', () => this.handleSendMessage());

    // 监听按键事件 (Enter 键发送消息)
    this.elements.messageInput.addEventListener('keydown', e => this.handleInputKey(e));

    // 监听模型选择器变化事件
    this.elements.modelSelector.addEventListener('change', e => this.handleModelChange(e.target.value));

    // 监听新建对话按钮
    this.elements.newChatBtn.addEventListener('click', () => this.createNewConversation());

    this.elements.conversationList.addEventListener('click', (e) => {
      const deleteBtn = e.target.closest('.delete-conv-btn');
      if (deleteBtn) {
        const convId = deleteBtn.dataset.convId;
        this.handleDeleteConversation(convId);
      }
    });
  }

  handleInputKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault(); // 防止换行
      this.handleSendMessage();
    }
  }

  async handleSendMessage() {
    const message = this.elements.messageInput.value.trim();
    if (!message || !this.currentConversationId || this.isProcessing) return;

    this.isProcessing = true;  // 设置为正在处理状态

    // 立即显示用户的消息
    this.renderNewMessage({
      role: 'user',
      content: message,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    });

    // 保存到 LocalStorage
    this.saveChatHistory(this.currentConversationId, 'user', message);

    // 清空输入框
    this.elements.messageInput.value = '';

    try {
      this.toggleLoading(true); // 显示加载状态

      // 获取当前对话的所有历史消息（历史对话记忆，新添加）
      const conversationMessages = JSON.parse(localStorage.getItem(this.currentConversationId)) || [];

      // 将历史消息和当前消息一起发送给模型（历史对话记忆，新添加）
      const payload = {
        conversation_id: this.currentConversationId,
        messages: [...conversationMessages, { role: 'user', content: message }],
        model: this.currentModel
      };

      // 发送消息到后端获取模型回复
      const response = await fetch('/api/chat/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': this.getCsrfToken()
        },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
      // 更精确的错误判断
      throw new Error(`消息发送失败: ${response.status}${response.statusText}`);
    }

      const data = await response.json();

      // 渲染模型的回复
      this.renderNewMessage({
        role: 'assistant',
        content: data.response,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      });

      // 更新对话标题
      this.updateConversationTitle(data.title);  // 使用返回的对话信息更新标题

      // 保存助手的回复到 LocalStorage
      this.saveChatHistory(this.currentConversationId, 'assistant', data.response);

    } catch (error) {
      console.error('发送消息失败:', error);
      alert('消息发送失败，请稍后再试');
    } finally {
      this.isProcessing = false;
      this.toggleLoading(false); // 隐藏加载状态
    }
  }

  // 切换加载状态
  toggleLoading(isLoading) {
    this.elements.loadingOverlay.style.display = isLoading ? "flex" : "none"; // 显示或隐藏加载中状态
    this.elements.sendBtn.disabled = isLoading;
    this.elements.newChatBtn.disabled = isLoading;
  }

  // 获取 CSRF token
  getCsrfToken() {
    const cookieValue = document.cookie.match(/csrftoken=([^;]+)/);
    return cookieValue ? cookieValue[1] : '';
  }

  // 处理模型选择变化
  handleModelChange(model) {
    this.currentModel = model;
    if (this.currentConversationId) {
      this.updateConversationModel();
    }
  }

  escapeHtml(text) {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
  }

  // 更新当前对话的模型
  async updateConversationModel() {
    try {
      const response = await fetch(`/api/conversations/${this.currentConversationId}/model/`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': this.getCsrfToken()
        },
        body: JSON.stringify({ model: this.currentModel })
      });
      if (!response.ok) throw new Error('模型更新失败');
    } catch (error) {
      console.error('模型更新失败:', error);
    }
  }

  // 渲染新消息
  renderNewMessage(message) {
    // 检查消息是否已经存在（避免重复渲染）
    const existingMessages = this.elements.chatMessages.querySelectorAll('.message');
    for (let existingMessage of existingMessages) {
      if (existingMessage.textContent === message.content) {
        return; // 如果消息已存在，则不渲染
      }
    }

    // const escapedContent = escapeHtml(message.content);
    let escapedContent = this.escapeHtml(message.content);
    // 将 <think> 和 </think> 转换为实体字符
    escapedContent = escapedContent.replace(/<think>/g, '&lt;think&gt;').replace(/<\/think>/g, '&lt;/think&gt;');

    const messageHTML = `
      <div class="message ${message.role}-message">
        <div class="message-content">${escapedContent}</div>
        <div class="message-footer">
          <span class="message-role">${message.role}</span>
          <time class="message-time">${message.time}</time>
        </div>
      </div>
    `;
    this.elements.chatMessages.insertAdjacentHTML('beforeend', messageHTML);
    this.scrollToBottom();
  }

  // 滚动到底部
  scrollToBottom() {
    this.elements.chatMessages.scrollTop = this.elements.chatMessages.scrollHeight;
  }

  // 创建新对话
  async createNewConversation() {
  try {
    const response = await fetch('/api/conversations/new/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.getCsrfToken()
      },
      // body: JSON.stringify({ model: this.currentModel })
      body: JSON.stringify({ model: this.currentModel })
    });

    if (!response.ok) throw new Error('新建对话失败');
    const data = await response.json();
    this.currentConversationId = data.id;

    // 清空聊天界面（新聊天界面，新添加）
    this.elements.chatMessages.innerHTML = '';

    // 刷新左侧边栏
    this.loadConversations();

  } catch (error) {
    console.error('新建对话失败:', error);
    alert('新建对话失败，请稍后重试');
  }
}


  // 加载所有对话
  async loadConversations() {
    try {
      const response = await fetch('/api/conversations/');
      if (!response.ok) throw new Error('加载对话列表失败');
      const conversations = await response.json();
      this.renderConversationList(conversations);
    } catch (error) {
      console.error('加载对话失败:', error);
      alert('加载对话失败，请稍后重试');
    }
  }

  // 渲染历史对话列表
  renderConversationList(conversations) {
    this.elements.conversationList.innerHTML = conversations
      .map(conv => `
        <div class="conversation-item ${conv.id === this.currentConversationId ? 'selected' : ''}" data-conv-id="${conv.id}">
          <div class="conv-header">
          <!-- 默认使用 '新对话' 如果标题为空 -->
            <h3 class="conv-title">${conv.title || '新对话'}</h3>
            <!-- 添加删除按钮 -->
            <button class="delete-conv-btn" aria-label="删除对话" data-conv-id="${conv.id}">×</button>
          </div>
          <div class="conv-meta">
            <span class="model-badge">${conv.model_name}</span>
            <time class="conv-time">${conv.created_at}</time>
          </div>
        </div>
      `).join('');

    // 给每个历史对话添加点击事件，点击时加载历史聊天（新聊天界面，新添加）
    this.elements.conversationList.querySelectorAll('.conversation-item').forEach(item => {
      item.addEventListener('click', () => {
        const convId = item.dataset.convId;
        this.loadConversationMessages(convId);  // 加载历史聊天
      });
    });
  }

  // 加载历史聊天消息（新聊天界面，新添加）
  async loadConversationMessages(convId) {
    try {
      // 清空当前聊天记录
      this.elements.chatMessages.innerHTML = '';

      // 获取并渲染该对话的历史消息
      const response = await fetch(`/api/conversations/${convId}/messages/`);
      if (!response.ok) {
        console.error("无法加载历史消息", response.status);   // 调试输出
        return;
      }

      const messages = await response.json();
      console.log("历史消息:", messages);  // 调试输出

      // 如果没有消息
      if (messages.length === 0) {
        console.log("没有历史消息可显示");  // 调试输出
      }

      // 渲染历史聊天消息
      messages.forEach(message => {
        this.renderNewMessage(message);
      });

      // 更新当前对话ID
      this.currentConversationId = convId;

      // 加载该对话的本地存储历史消息
      this.loadChatHistory(convId);

    } catch (error) {
      console.error('加载历史聊天失败:', error);
      alert('加载历史聊天失败，请稍后重试');
    }
  }


  // 加载可用模型
  async loadAvailableModels() {
    try {
      const response = await fetch('/api/models/');
      const models = await response.json();
      this.populateModelSelector(models);
    } catch (error) {
      console.error('加载模型失败:', error);
      alert('模型加载失败，请稍后重试');
    }
  }

  // 填充模型选择器
  populateModelSelector(models) {
    const selector = this.elements.modelSelector;
    selector.innerHTML = models
      .map(model => `<option value="${model}">${model}</option>`)
      .join('');
  }

  // 删除左侧对话记录（新添加，回滚删除）
  async handleDeleteConversation(convId) {
    try {
      const response = await fetch(`/api/conversations/${convId}/delete/`, {
        method: 'DELETE',
        headers: {
          'X-CSRFToken': this.getCsrfToken()
        }
      });

      if (!response.ok) throw new Error('删除对话失败');

      // 从 UI 中移除该对话
      const conversationElement = this.elements.conversationList.querySelector(`[data-conv-id="${convId}"]`);
      if (conversationElement) {
        conversationElement.remove();
      }

      // 如果删除的对话是当前选中的对话，清空聊天内容
      if (this.currentConversationId === convId) {
        this.elements.chatMessages.innerHTML = '';
        this.currentConversationId = null;  // 清除当前对话 ID
      }
    } catch (error) {
      console.error('删除对话失败:', error);
      alert('删除对话失败，请稍后重试');
    }
  }

  saveChatHistory(convId, role, content) {
    const chatHistory = JSON.parse(localStorage.getItem(convId)) || [];
    localStorage.setItem(`chatHistory_${convId}`, JSON.stringify(chatHistory));

    // 检查消息是否已存在，避免重复
    const existingMessage = chatHistory.find(msg => msg.content === content);
    if (existingMessage) return;  // 如果消息已存在，不保存

    chatHistory.push({
      role,
      content,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    });
    localStorage.setItem(convId, JSON.stringify(chatHistory)); // 按对话 ID 存储历史消息
  }


  // 加载历史消息
  loadChatHistory(convId) {
    // 清空当前聊天记录
    this.elements.chatMessages.innerHTML = '';

    // 获取并渲染该对话的历史消息
    const chatHistory = JSON.parse(localStorage.getItem(convId)) || [];
    // const chatHistory = JSON.parse(localStorage.getItem(`chatHistory_${convId}`)) || [];
    chatHistory.forEach(message => {
      this.renderNewMessage(message); // 渲染历史消息
    });
  }


  async initializeApp() {
    try {
      // 加载模型列表
      await this.loadAvailableModels();
      await this.loadConversations();
    } catch (error) {
      alert('初始化失败，请稍后重试');
    }
  }

  async updateConversationTitle(conversation) {
    try {
      // 更新对话标题
      const newTitle = conversation.title || '新对话';  // 默认使用"新对话"作为标题

      // 更新页面上的对话标题元素
      const conversationElement = document.querySelector(`[data-conv-id="${this.currentConversationId}"] .conv-title`);
      if (conversationElement) {
        conversationElement.textContent = newTitle;
      }

    } catch (error) {
      console.error('更新标题失败:', error);
    }
  }

}

// 在页面加载时实例化 ChatApplication 类
document.addEventListener('DOMContentLoaded', () => {
  const chatApp = new ChatApplication();
  chatApp.loadChatHistory();  // 加载历史消息
});

// // 假设这是处理对话响应的函数
// function handleChatResponse(response) {
//   if (response.title) {
//     // 如果有新标题，更新对话标题
//     ChatApplication.updateConversationTitle(response.title);
//   }
// }
//
// // 调用处理对话响应的函数
// handleChatResponse(conversation);

