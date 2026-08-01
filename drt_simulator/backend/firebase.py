"""Render 환경에서 Firebase Admin SDK를 안전하게 초기화한다."""

import json

import firebase_admin
from firebase_admin import credentials, firestore

from backend.config import BackendSettings


def initialize_firestore(settings: BackendSettings) -> firestore.Client:
    """환경변수 JSON 또는 ADC로 Firebase와 Firestore를 초기화한다."""

    if not firebase_admin._apps:
        options = {"projectId": settings.firebase_project_id} if settings.firebase_project_id else None
        if settings.firebase_credentials_json:
            credential_info = json.loads(settings.firebase_credentials_json)
            firebase_admin.initialize_app(credentials.Certificate(credential_info), options=options)
        else:
            firebase_admin.initialize_app(options=options)
    return firestore.client()
