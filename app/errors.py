"""Ошибки бизнес-логики. Сервисы не знают про HTTP; коды назначаются здесь."""


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class InvalidDataError(AppError):
    status_code = 422


class PermissionDeniedError(AppError):
    status_code = 403
