from django.urls import path
from . import views

urlpatterns = [
    path('', views.event_list, name='event_list'),
    path('event/<int:event_pk>/rsvp/', views.rsvp_form, name='rsvp_form'),
    path('rsvp/<int:rsvp_pk>/confirmation/', views.rsvp_confirmation, name='rsvp_confirmation'),
    path('invite/<uuid:token>/', views.invited_rsvp, name='invited_rsvp'),
    path('event/<int:event_pk>/placecards/', views.placecards, name='placecards'),
]
