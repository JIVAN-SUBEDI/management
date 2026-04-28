from rest_framework import serializers


class SendMessageSerializer(serializers.Serializer):
    content = serializers.CharField(allow_blank=True)
    echo_id = serializers.CharField(required=False, allow_blank=True)
    private = serializers.BooleanField(required=False, default=False)
    reply_to_message_id = serializers.IntegerField(required=False, allow_null=True)


class TypingSerializer(serializers.Serializer):
    typing_status = serializers.ChoiceField(choices=["on", "off"])


class MessageListSerializer(serializers.Serializer):
    before = serializers.IntegerField(required=False)
    after = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if attrs.get("before") and attrs.get("after"):
            raise serializers.ValidationError("Use either before or after, not both.")
        return attrs
class MessageActionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["reaction", "reply"])
    reaction = serializers.ChoiceField(
        choices=["👍", "❤️", "😂", "😮", "😢", "🙏"],
        required=False,
        allow_null=True,
    )
    content = serializers.CharField(required=False, allow_blank=True)
    