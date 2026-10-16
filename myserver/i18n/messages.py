"""Simple i18n layer. Currently English is primary; Arabic is scaffolded.

Usage:
    from myserver.i18n import t
    print(t("services_started"))
"""
from __future__ import annotations

import os

_LANG = os.environ.get("MYSERVER_LANG", "en").lower()
if _LANG not in ("en", "ar"):
    _LANG = "en"


MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "services_started":      "Services started successfully.",
        "services_stopped":      "All services stopped.",
        "services_some_left":    "Some services refused to stop.",
        "web_root_missing":      "Web root missing: {path}",
        "backup_created":        "Backup created: {path}",
        "restore_complete":      "Restore complete.",
        "update_available":      "Update available: {old} -> {new}",
        "update_latest":         "Already on latest ({version}).",
        "live_started":          "Live Reload enabled.",
        "live_stopped":          "Live Reload disabled.",
        "ssl_self_signed_note":  "Note: HTTPS uses a self-signed certificate.",
        "confirm_continue":      "Continue?",
    },
    "ar": {
        "services_started":      "تم تشغيل جميع الخدمات بنجاح.",
        "services_stopped":      "تم إيقاف جميع الخدمات.",
        "services_some_left":    "بعض الخدمات لم تتوقف.",
        "web_root_missing":      "مجلد الويب مفقود: {path}",
        "backup_created":        "تم إنشاء نسخة احتياطية: {path}",
        "restore_complete":      "تمت الاستعادة بنجاح.",
        "update_available":      "يتوفر تحديث: {old} -> {new}",
        "update_latest":         "أنت على أحدث إصدار ({version}).",
        "live_started":          "تم تفعيل إعادة التحميل التلقائي.",
        "live_stopped":          "تم تعطيل إعادة التحميل التلقائي.",
        "ssl_self_signed_note":  "ملاحظة: شهادة HTTPS موقّعة ذاتيًا.",
        "confirm_continue":      "هل تريد المتابعة؟",
    },
}


def set_language(lang: str) -> None:
    global _LANG
    if lang.lower() in MESSAGES:
        _LANG = lang.lower()


def current_language() -> str:
    return _LANG


def t(key: str, **kwargs) -> str:
    table = MESSAGES.get(_LANG) or MESSAGES["en"]
    text = table.get(key) or MESSAGES["en"].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text