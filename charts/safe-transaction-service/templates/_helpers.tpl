{{/*
Expand the name of the chart.
*/}}
{{- define "safe-transaction.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "safe-transaction.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "safe-transaction.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Default labels
*/}}
{{- define "safe-transaction.labels" -}}
helm.sh/chart: {{ include "safe-transaction.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/name: {{ .Release.Name }}
app.kubernetes.io/instance: {{ include "safe-transaction.name" . }}

{{- end }}

{{/*
Postgres Secret
*/}}
{{- define "safe-transaction.postgres-secret" -}}
{{- if .Values.config.postgres.secretReferenceKey -}}
{{- .Values.config.postgres.secretReferenceKey }}
{{- else -}}
{{ include "safe-transaction.name" . }}-postgres
{{- end -}}
{{- end -}}

{{/*
Redis Secret
*/}}
{{- define "safe-transaction.redis-secret" -}}
{{- if .Values.config.redis.secretReferenceKey -}}
{{- .Values.config.redis.secretReferenceKey }}
{{- else -}}
{{ include "safe-transaction.name" . }}-redis
{{- end -}}
{{- end -}}

{{/*
RabbitMQ Secret
*/}}
{{- define "safe-transaction.rabbitmq-secret" -}}
{{- if .Values.config.rabbitmq.secretReferenceKey -}}
{{- .Values.config.rabbitmq.secretReferenceKey -}}
{{- else -}}
{{ include "safe-transaction.name" . }}-rabbitmq
{{- end -}}
{{- end -}}