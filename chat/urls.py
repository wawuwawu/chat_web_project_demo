# chat/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_view, name='chat_home'),
    path('chat/', views.chat_view, name='chat'),
    path('api/chat/', views.chat, name='api_chat'),
    path('api/models/', views.get_models, name='get_models'),
    # path('conversations/<int:conv_id>/model/', views.update_conversation_model, name='update_model'),
    path('api/conversations/', views.get_conversations, name='get_conversations'),
    path('api/conversations/new/', views.new_conversation, name='new_conversation'),
    path('api/conversations/<int:conv_id>/delete/', views.delete_conversation, name='delete_conversation'),
    path('api/conversations/<int:conv_id>/messages/', views.get_conversation_messages, name='get_conversation_messages'),
    # 更新对话标题的路由
    path('api/conversations/<int:conv_id>/title/', views.update_conversation_title, name='update_conversation_title'),
    # 更新模型的路由
    path('api/conversations/<int:conv_id>/model/', views.update_conversation_model, name='update_model'),
]

