from django.db import models

class Conversation(models.Model):
    title = models.CharField(max_length=100)
    model_name = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    is_title_generated = models.BooleanField(default=False)

    def __str__(self):
        return self.title


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, related_name='messages', on_delete=models.CASCADE)
    role = models.CharField(max_length=50)  # "user" or "assistant"
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.role}: {self.content[:20]}"  # 显示消息的前20个字符

