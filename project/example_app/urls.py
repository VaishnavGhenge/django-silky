from django.urls import path

from . import views

app_name = 'example_app'
urlpatterns = [
    path(route='', view=views.index, name='index'),
    path(route='create', view=views.ExampleCreateView.as_view(), name='create'),
    path(route='api/blinds/', view=views.api_blind_list, name='api_blind_list'),
    path(route='api/blinds/create/', view=views.api_blind_create, name='api_blind_create'),
    path(route='api/blinds/stats/', view=views.api_blind_stats, name='api_blind_stats'),
    path(route='api/blinds/<int:pk>/', view=views.api_blind_detail, name='api_blind_detail'),
]
