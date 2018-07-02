import json
import os

from rest_framework import exceptions, status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import CoreJSONRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.schemas import SchemaGenerator
from rest_framework.views import APIView
from rest_framework_swagger.renderers import OpenAPICodec
from rest_framework_swagger.renderers import \
    OpenAPIRenderer as BaseOpenAPIRenderer
from rest_framework_swagger.renderers import \
    SwaggerUIRenderer as BaseSwaggerUIRenderer
from rest_framework_swagger.settings import swagger_settings as settings


def get_swagger_view(title=None, url=None, patterns=None, urlconf=None):
    """
    Returns schema view which renders Swagger/OpenAPI.
    """
    class OpenAPIRenderer(BaseOpenAPIRenderer):

        def render(self, data, accepted_media_type=None, renderer_context=None):
            if renderer_context['response'].status_code != status.HTTP_200_OK:
                return JSONRenderer().render(data)

            request_scheme = renderer_context['request']._request._get_scheme()
            scheme = os.getenv('SWAGGER_SCHEME_PROTOCOL', request_scheme)
            self.scheme = scheme

            options = self.get_customizations()
            return OpenAPICodec().encode(data, **options)

        def get_customizations(self, *args, **kwargs):
            data = super(OpenAPIRenderer, self).get_customizations()
            data["schemes"] = [self.scheme]
            return data

    class SwaggerUIRenderer(BaseSwaggerUIRenderer):

        def set_context(self, data, renderer_context):
            renderer_context['USE_SESSION_AUTH'] = settings.USE_SESSION_AUTH
            renderer_context.update(self.get_auth_urls())

            drs_settings = self.get_ui_settings()
            renderer_context['drs_settings'] = json.dumps(drs_settings)
            renderer_context['spec'] = OpenAPIRenderer().render(
                data=data,
                renderer_context=renderer_context
            ).decode()

    class SwaggerSchemaView(APIView):
        _ignore_model_permissions = True
        exclude_from_schema = True
        permission_classes = [AllowAny]
        renderer_classes = [
            CoreJSONRenderer,
            OpenAPIRenderer,
            SwaggerUIRenderer
        ]

        def get(self, request):
            generator = SchemaGenerator(
                title=title,
                url=url,
                patterns=patterns,
                urlconf=urlconf
            )
            schema = generator.get_schema(request=request)

            if not schema:
                raise exceptions.ValidationError(
                    'The schema generator did not return a schema Document'
                )

            return Response(schema)

    return SwaggerSchemaView.as_view()
