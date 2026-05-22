def _trigger_modal_worker(
    transcription_id: int,
    job_type: str = "process",
    detection_sensitivity: str | None = None,
    track_id: int | None = None,
) -> None:
    modal_trigger_url = core.config.settings.MODAL_TRIGGER_URL
    session = db.SessionLocal()
    try:
        transcription = session.query(models.Transcription).filter(
            models.Transcription.id == transcription_id
        ).first()
        if not transcription or transcription.is_deleted:
            logger.info(
                "Skipping Modal dispatch because transcription %s is missing or deleted.",
                transcription_id,
            )
            return

        if transcription.processing_status != "processing":
            logger.info(
                "Skipping Modal dispatch for transcription %s with status %s.",
                transcription_id,
                transcription.processing_status,
            )
            return

        retry_at = _as_aware_utc(transcription.modal_retry_at)
        if retry_at and retry_at > datetime.now(timezone.utc):
            logger.info(
                "Skipping Modal dispatch for transcription %s until retry time %s.",
                transcription_id,
                retry_at,
            )
            return

        if (
            transcription.modal_dispatch_status == "dispatched"
            and transcription.modal_request_id
            and transcription.modal_job_type == job_type
        ):
            logger.info(
                "Skipping duplicate Modal dispatch for transcription %s request %s.",
                transcription_id,
                transcription.modal_request_id,
            )
            return

        if not modal_trigger_url:
            transcription.processing_status = "queued"
            transcription.queue_position = None
            transcription.estimated_wait_time = None
            transcription.modal_dispatch_status = "missing_trigger_url"
            transcription.modal_job_type = job_type
            session.add(transcription)
            session.commit()
            logger.info(
                "PROCESSING_MODE=modal but MODAL_TRIGGER_URL is not configured; "
                "transcription %s remains queued.",
                transcription_id,
            )
            return

        transcription.modal_request_id = transcription.modal_request_id or str(uuid.uuid4())
        transcription.modal_job_type = job_type
        old_retry_at = transcription.modal_retry_at

        transcription.modal_dispatch_status = "dispatched"
        transcription.modal_dispatched_at = datetime.now(timezone.utc)
        transcription.modal_retry_at = None
        transcription.celery_task_id = None
        session.add(transcription)
        session.commit()
        session.refresh(transcription)

        headers = {}
        if core.config.settings.WORKER_API_TOKEN:
            headers["Authorization"] = f"Bearer {core.config.settings.WORKER_API_TOKEN}"

        try:
            response = httpx.post(
                modal_trigger_url,
                json=_build_worker_payload_for_modal(
                    transcription,
                    job_type=job_type,
                    detection_sensitivity=detection_sensitivity,
                    track_id=track_id,
                ),
                headers=headers,
                timeout=120.0,
            )
            logger.info(
                "Modal dispatch attempt: transcription_id=%s, job_type=%s, "
                "status_code=%s, retry_count=%s, retry_at=%s, modal_request_id=%s",
                transcription_id,
                job_type,
                response.status_code,
                transcription.modal_retry_count,
                old_retry_at,
                transcription.modal_request_id,
            )

            if response.status_code == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = int(retry_after_header) if retry_after_header else None
                except ValueError:
                    retry_after = None
                _mark_modal_retry(
                    transcription,
                    session,
                    error="Modal is rate limited. This job will retry automatically.",
                    retry_after_seconds=retry_after,
                    rate_limited=True,
                )
                logger.warning(
                    "Modal rate limited transcription %s; queued retry.",
                    transcription_id,
                )
                return

            response.raise_for_status()
            logger.info("Triggered Modal worker for transcription %s", transcription_id)
        except Exception as exc:
            logger.exception(
                "Modal dispatch attempt failed for transcription %s.",
                transcription_id,
            )
            try:
                transcription = session.query(models.Transcription).filter(
                    models.Transcription.id == transcription_id
                ).first()
                if transcription and transcription.processing_status == "processing":
                    _mark_modal_retry(
                        transcription,
                        session,
                        error="Modal dispatch failed. This job will retry automatically.",
                    )
            except Exception:
                logger.exception(
                    "Failed to mark retry state for transcription %s after dispatch error.",
                    transcription_id,
                )
                session.rollback()
            logger.error(
                "Modal trigger failed for transcription %s; leaving job queued.",
                transcription_id,
            )
    finally:
        session.close()
