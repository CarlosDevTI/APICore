from django.urls import path
from .views import ValidarView

urlpatterns = [
    path('consulta-automatica/', ValidarView.as_view(), name='consulta-automatica'),
]