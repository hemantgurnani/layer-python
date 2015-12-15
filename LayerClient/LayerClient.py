# -*- coding: utf-8 -*-
import dateutil.parser
import requests
import json

from urlparse import urlparse

MIME_TEXT_PLAIN = 'text/plain'

METHOD_GET = 'GET'
METHOD_POST = 'POST'
METHOD_DELETE = 'DELETE'

LAYER_URI_ANNOUNCEMENTS = 'announcements'
LAYER_URI_CONVERSATIONS = 'conversations'
LAYER_URI_MESSAGES = 'messages'


class LayerPlatformException(Exception):

    def __init__(self, message, http_code=None, code=None, error_id=None):
        super(LayerPlatformException, self).__init__(message)
        self.http_code = http_code
        self.code = code
        self.error_id = error_id


class BaseLayerResponse:
    """
    Base class for several of the datatypes returned by Layer - if it returns
    an ID and a URL, it should extend this class in order to get UUID parsing.
    """

    def uuid(self):
        """
        When we get a conversation response from the server, it doesn't include
        the raw UUID, only a URI of the form:
            layer:///conversations/f3cc7b32-3c92-11e4-baad-164230d1df67
        which must be parsed to retrieve the UUID for easy reference.
        """
        uri = urlparse(self.id)
        path_parts = uri.path.split('/')
        if len(path_parts) == 3 and len(path_parts[2]) == 36:
            return path_parts[2]

        return None

    @staticmethod
    def parse_date(date):
        """
        Convert an ISO 8601 datestamp format to a Python date object.

        Parameter `date`: A string datestamp in ISO 8601 format. May be None.
        Return: A datetime, or None if the date string was empty.
        """

        if not date:
            return None

        return dateutil.parser.parse(date)


class PlatformClient(object):
    """
    Client to the server-side layer API
    """

    def __init__(self, app_uuid, bearer_token):
        """
        Create a new Layer platform client.

        Parameters:
        - `app_uuid`: The UUID for the application
        - `bearer_token`: A Layer authorization token, as generated by the
            Developer dashboard
        """
        self.app_uuid = app_uuid
        self.bearer_token = bearer_token

    def _get_layer_headers(self):
        """
        Convenience method for retrieving the default set of authenticated
        headers.

        Return: The headers required to authorize ourselves with the Layer
        platform API.
        """
        return {
            'Accept': 'application/vnd.layer+json; version=1.0',
            'Authorization': 'Bearer ' + self.bearer_token,
            'Content-Type': 'application/json'
        }

    def _get_layer_uri(self, *suffixes):
        """
        Used for building Layer URIs for different API endpoints.

        Parameter`suffixes`: An array of strings, which will be joined as the
            end portion of the URI body.

        Return: A complete URI for an endpoint with optional arguments
        """
        suffix_string = '/'.join(suffixes) if suffixes else ''
        return 'https://api.layer.com/apps/{app_id}/{suffix}'.format(
            app_id=self.app_uuid,
            suffix=suffix_string,
        )

    def _raw_request(self, method, url, data=None):
        """
        Actually make a call to the Layer API.
        If the response does not come back as valid, raises a
        LayerPlatformException with the error data from Layer.

        Parameters:
        - `method`: The HTTP method to use
        - `url`: The target URL
        - `data`: Optional post body. Must be json encodable.

        Return: Raw JSON doc of the Layer API response

        Exception: `LayerPlatformException` if the API returns non-OK response
        """
        result = requests.request(
            method,
            url,
            headers=self._get_layer_headers(),
            data=(json.dumps(data) if data else None)
        )

        if result.ok:
            return result.json()

        try:
            error = result.json()
            raise LayerPlatformException(
                error.get('message'),
                http_code=result.status_code,
                code=error.get('code'),
                error_id=error.get('id'),
            )
        except ValueError:
            # Catches the JSON decode error for failures that do not have
            # associated data
            raise LayerPlatformException(
                result.text,
                http_code=result.status_code,
            )

    def get_conversation(self, conversation_uuid):
        """
        Fetch an existing conversation by UUID

        Parameter `conversation_uuid`: The UUID of the conversation to fetch

        Return: A `Conversation` instance
        """
        return Conversation.from_dict(
            self._raw_request(
                METHOD_GET,
                self._get_layer_uri(
                    LAYER_URI_CONVERSATIONS,
                    conversation_uuid,
                ),
            )
        )

    def delete_conversation(self, conversation_uuid):
        """
        Delete a conversation. Affects all users in the conversation across all
        of their devices.

        Parameter `conversation_uuid`: The uuid of the conversation to delete
        """
        self._raw_request(
            METHOD_DELETE,
            self._get_layer_uri(
                LAYER_URI_CONVERSATIONS,
                conversation_uuid,
            ),
        )

    def create_conversation(self, participants, distinct=True, metadata=None):
        """
        Create a new converstaion.

        Parameters:
        - `participants`: An array of participant IDs (strings)
        - `distinct`: Whether or not we should create a new conversation for
            the participants, or re-use one if one exists. Will return an
            existing conversation if distinct=True.
        - `metadata`: Unstructured data to be passed through to the client.
            This data must be json-serializable.

        Return: A new `Conversation` instance
        """
        return Conversation.from_dict(
            self._raw_request(
                METHOD_POST,
                self._get_layer_uri(
                    LAYER_URI_CONVERSATIONS,
                ),
                {
                    'participants': participants,
                    'distinct': distinct,
                    'metadata': metadata,
                }
            )
        )

    def send_message(self, conversation, sender, message_parts,
                     notification=None):
        """
        Send a message to a conversation.

        Parameters:
        - `conversation`: A `LayerClient.Conversation` instance for the
        conversation we wish to send to
        - `sender`: A `LayerClient.Sender` instance
        - `message_parts`: An array of `LayerClient.MessagePart` objects
        - `notification`: Optional `PushNotification` instance.

        Return: A new Message instance, or None if we were passed invalid
        (None) arguments.
        """

        if not conversation or not sender or not message_parts:
            return None

        request_data = {
            'sender': sender.as_dict(),
            'parts': [
                part.as_dict() for part in message_parts
            ],
        }
        if notification:
            request_data['notification'] = notification.as_dict()

        return Message.from_dict(
            self._raw_request(
                METHOD_POST,
                self._get_layer_uri(
                    LAYER_URI_CONVERSATIONS,
                    conversation.uuid(),
                    LAYER_URI_MESSAGES,
                ),
                request_data,
            )
        )

    def send_announcement(self, sender, recipients, message_parts,
                          notification=None):
        """
        Send an announcement to a list of users.

        Parameters:
        - `sender`: A `LayerClient.Sender` instance. The sender must have a
            name, as this endpoint cannot be used with a sender ID.
        - 'recipients`: A list of strings, each of which is a recipient ID.
        - `message_parts`: An array of `LayerClient.MessagePart` objects
        - `notification`: Optional `PushNotification` instance.
        """
        request_data = {
            'sender': {
                'name': sender.name,
            },
            'parts': [
                part.as_dict() for part in message_parts
            ],
            'recipients': recipients,
        }
        if notification:
            request_data['notification'] = notification.as_dict()

        return Announcement.from_dict(
            self._raw_request(
                METHOD_POST,
                self._get_layer_uri(LAYER_URI_ANNOUNCEMENTS),
                request_data,
            )
        )


class Announcement(BaseLayerResponse):
    """
    Contains the data returned from the API when sending an Announcement
    """

    def __init__(self, id, url, sent_at, recipients, sender, parts):
        self.id = id
        self.url = url
        self.sent_at = sent_at
        self.recipients = recipients
        self.sender = sender
        self.parts = parts

    @staticmethod
    def from_dict(dict_data):
        return Announcement(
            dict_data.get('id'),
            dict_data.get('url'),
            Announcement.parse_date(dict_data.get('sent_at')),
            dict_data.get('recipients'),
            Sender.from_dict(dict_data.get('sender')),
            [
                MessagePart.from_dict(part) for part in dict_data.get('parts')
            ],
        )

    def __repr__(self):
        return '<LayerClient.Announcement "{text}">'.format(
            text=self.uuid()
        )


class Message(BaseLayerResponse):
    """
    The response returned by the API when a message is sent.
    """

    def __init__(self, id, url, sent_at=None, sender=None,
                 conversation=None, parts=None, recipient_status=None):
        self.id = id
        self.url = url
        self.sent_at = sent_at
        self.sender = sender
        self.conversation = conversation
        self.parts = parts
        self.recipient_status = recipient_status

    @staticmethod
    def from_dict(dict_data):
        return Message(
            dict_data.get('id'),
            dict_data.get('url'),
            Message.parse_date(dict_data.get('sent_at')),
            Sender.from_dict(dict_data.get('sender')),
            Conversation.from_dict(dict_data.get('conversation')),
            [
                MessagePart.from_dict(part) for part in dict_data.get('parts')
            ],
            dict_data.get('recipient_status'),
        )

    def __repr__(self):
        return '<LayerClient.Message "{uuid}">'.format(
            uuid=self.uuid()
        )


class Sender:
    """
    Used for sending messages.
    Id and Name may both be set, but the send_message API will prefer
    one over the other.
    """

    def __init__(self, id=None, name=None):
        self.id = id
        self.name = name

    @staticmethod
    def from_dict(json):
        if not json:
            return None

        return Sender(
            json.get('id'),
            json.get('name'),
        )

    def __repr__(self):
        return '<LayerClient.Sender "{name}" (id: {id})>'.format(
            id=self.id,
            name=self.name,
        )

    def as_dict(self):
        # If both ID and name are set, we will default to only the ID.
        # The layer platform explicitly prohibits sending both.
        if self.id:
            return {
                'user_id': self.id,
            }
        else:
            return {
                'name': self.name,
            }


class MessagePart:
    """
    A message chunk, as used for sending messages.

    Message chunks are currently limited to 2KiB by Layer. If a message is
    larger, it must be broken into several chunks.
    By default, chunks are text/plain but can be any format.
    Messages that are non-text (e.g. images) can be sent as base64. In this
    case, the encoding field must be set.
    """

    def __init__(self, body, mime=MIME_TEXT_PLAIN, encoding=None):
        self.body = body
        self.mime_type = mime
        self.encoding = encoding

    @staticmethod
    def from_dict(dict_data):
        return MessagePart(
            dict_data.get('body'),
            dict_data.get('mime_type'),
            dict_data.get('encoding'),
        )

    def __repr__(self):
        return (
            '<LayerClient.MessagePart "{body}"{mime}{encoding}>'
            .format(
                body=self.body,
                mime=' Content-Type: {0}'.format(self.mime_type),
                encoding=(
                    ' Encoding: {0}'.format(self.encoding) if self.encoding
                    else ''
                )
            )
        )

    def as_dict(self):
        data = {
            'body': self.body,
            'mime_type': self.mime_type,
        }
        if self.encoding:
            data['encoding'] = self.encoding

        return data


class PushNotification:
    """
    Details for a push notification sent as part of a conversation message.
    Each push notification must have a body.
    Sound and recipients are optional. For Android, the sound parameter is
    simply sent to the client as a string.
    The recipients field is a map of user id to PushNotification object,
    allowing for one push notification to have custom settings for certain
    users. PushNotification instances used as part of the recipients field
    should not themselves have the recipient field set.
    """

    def __init__(self, text, sound=None, recipients=None):
        self.text = text
        self.sound = sound
        self.recipients = recipients

    def __repr__(self):
        return '<LayerClient.PushNotification "{text}">'.format(
            text=self.text
        )

    def as_dict(self):
        data = {
            'text': self.text,
        }
        if self.sound:
            data['sound'] = self.sound

        # If per-recipient push notification instances are present, convert
        # them to dictionaries as well. We don't simply recurse here to
        # ensure that we do not have child PushNotifications with their own
        # recipients fields.
        if self.recipients:
            recipients_dict = {}
            for recipient, notification in self.recipients.iteritems():
                recipients_dict[recipient] = {
                    'text': notification.text,
                    'sound': notification.sound,
                }
            data['recipients'] = self.recipients

        return data


class Conversation(BaseLayerResponse):
    """
    Represents a Layer conversation. Returned by the get_ and create_
    conversation methods.
    """

    def __init__(self, id, url, messages_url=None, created_at=None,
                 participants=[], distinct=False, metadata=None):
        self.id = id
        self.url = url
        self.messages_url = messages_url
        self.created_at = created_at
        self.participants = participants
        self.distinct = distinct
        self.metadata = metadata

    @staticmethod
    def from_dict(dict_data):
        created_at = (
            dateutil.parser.parse(dict_data.get('created_at'))
            if dict_data.get('created_at') else None
        )
        return Conversation(
            dict_data.get('id'),
            dict_data.get('url'),
            dict_data.get('messages_url'),
            created_at,
            dict_data.get('participants'),
            dict_data.get('distinct'),
            dict_data.get('metadata'),
        )

    def __repr__(self):
        return '<LayerClient.Conversation "{uuid}">'.format(
            uuid=self.uuid()
        )
