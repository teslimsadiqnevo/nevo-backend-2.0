from typing import Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    auth_password_pepper: SecretStr
    auth_pin_pepper: SecretStr
    auth_session_pepper: SecretStr

    @field_validator(
        "auth_password_pepper",
        "auth_pin_pepper",
        "auth_session_pepper",
    )
    @classmethod
    def validate_pepper_length(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("auth peppers must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_peppers_are_distinct(self) -> Self:
        values = {
            self.auth_password_pepper.get_secret_value(),
            self.auth_pin_pepper.get_secret_value(),
            self.auth_session_pepper.get_secret_value(),
        }
        if len(values) != 3:
            raise ValueError("password, PIN, and session peppers must be distinct")
        return self
