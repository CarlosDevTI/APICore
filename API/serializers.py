from rest_framework import serializers

class ValidarSerializer(serializers.Serializer):
    cedula = serializers.CharField(max_length=20)  
    tipo_identificacion = serializers.CharField(max_length=10)  
