# ADR 0010: Telegram is outbound only

Status: accepted.

Telegram implements only `NotificationSender`. No webhook, polling, command parser, trade action,
database credential, or exchange credential is permitted. The adapter is disabled by default and
uses environment configuration.
