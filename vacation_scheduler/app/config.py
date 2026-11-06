from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = 'Vacation Scheduler'
    secret_key: str = 'CHANGE_ME_BEFORE_DEPLOYMENT'
    database_url: str = 'postgresql+psycopg://vacation:vacation@db:5432/vacation'
    storage_path: str = '/storage'
    debug: bool = False
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

settings = Settings()
