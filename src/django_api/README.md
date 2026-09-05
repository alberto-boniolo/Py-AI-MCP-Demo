### Running

Database start in case container is stopped

```powershell
docker compose ps
```
or
```powershell
docker compose up -d
```


run django

```powershell
cd src\django_api
uv run python manage.py runserver
```

Stop postgres database for test

```powershell
docker compose stop postgres
```
or
```powershell
docker compose down
```
data are still persisted