"""Validated filters shared by the two authenticated log lists."""
from django.db.models import Q
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination

from .models import DeviceLog, SystemLog


class LogPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100


class LogFilters(serializers.Serializer):
    start_time = serializers.DateTimeField(required=False)
    end_time = serializers.DateTimeField(required=False)
    level = serializers.ChoiceField(choices=DeviceLog.LEVEL_CHOICES, required=False, allow_blank=True)
    device_id = serializers.CharField(required=False, allow_blank=True, max_length=100)
    module = serializers.CharField(required=False, allow_blank=True, max_length=40)
    actor = serializers.CharField(required=False, allow_blank=True, max_length=150)
    result = serializers.ChoiceField(choices=['submitted', 'success', 'failed', ''], required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate(self, attrs):
        if attrs.get('start_time') and attrs.get('end_time') and attrs['start_time'] > attrs['end_time']:
            raise serializers.ValidationError('开始时间不能晚于结束时间')
        return attrs


def filter_logs(queryset, params, platform=False):
    """Apply only validated, parameterized ORM predicates."""
    schema = LogFilters(data=params)
    schema.is_valid(raise_exception=True)
    filters = schema.validated_data
    for name, lookup in [('start_time', 'timestamp__gte'), ('end_time', 'timestamp__lte'), ('level', 'level')]:
        if filters.get(name):
            queryset = queryset.filter(**{lookup: filters[name]})
    if filters.get('device_id'):
        queryset = queryset.filter(**{'device_id' if platform else 'device__device_id': filters['device_id']})
    if platform:
        for name in ('module', 'result'):
            if filters.get(name):
                queryset = queryset.filter(**{name: filters[name]})
        if filters.get('actor'):
            queryset = queryset.filter(actor__icontains=filters['actor'])
    if filters.get('search'):
        predicate = Q(message__icontains=filters['search'])
        if platform:
            predicate |= Q(target__icontains=filters['search']) | Q(action__icontains=filters['search'])
        queryset = queryset.filter(predicate)
    return queryset.order_by('-timestamp', '-id')


class SystemLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemLog
        exclude = ['event_key']
