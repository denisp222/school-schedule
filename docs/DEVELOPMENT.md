# Разработка и сборка

Настольная версия рассчитана на Windows 10/11 x64. Для разработки используется Python 3.13. Установщик содержит среду выполнения; конечному пользователю Python не нужен.

## Локальный запуск

Команды для PowerShell из каталога проекта:

```powershell
git clone https://github.com/denisp222/school-schedule.git
cd school-schedule
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
git config core.hooksPath .githooks
```

Подготовьте официальные компоненты окна и сборки, затем запустите приложение:

```powershell
.venv\Scripts\python.exe tools/prepare_public_build.py
.venv\Scripts\python.exe launch.py
```

Подготовка загружает WebView2, среду .NET и инструменты установщика; для этого нужен интернет. Исходная публичная версия создаёт пустой проект. `app/demo_seed.json` — искусственный пример для разработки, он не используется как начальная школьная база и не входит в публичную сборку.

Чтобы отделить экспериментальный проект от других локальных данных, задайте отдельную папку перед запуском:

```powershell
$env:SCHEDULE_DATA = Join-Path $PWD 'build\development-data'
.venv\Scripts\python.exe launch.py
```

## Проверки

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools/check_repository.py --staged
.venv\Scripts\python.exe tools/check_repository.py --history
```

Тесты используют искусственные данные. Проверка репозитория проверяет пути, ключи и, при наличии частного локального seed-файла, фамилии из него. Она не заменяет ручную проверку новых данных и изображений.

Изображение `docs/media/schedule-demo.png` создано в изолированном демонстрационном проекте: классы и кабинеты вымышлены, преподаватели обозначены как «Учитель 01» и т. д. Другие изображения из рабочих папок не предназначены для публикации.

## Структура

```text
app/             Модель данных, API, расчёт и отчёты
app/static/      HTML, CSS, JavaScript и значки интерфейса
tests/           Автоматические проверки на искусственных данных
tools/           Проверки публикации, сборка и выпуск обновлений
docs/            Документация проекта
.github/         Проверки исходников и выпуск Windows-версии
desktop.py       Запуск локального сервиса и окна приложения
native_window.py Оболочка WinForms / WebView2
launch.py        Точка входа
```

## Публичная сборка

```powershell
.venv\Scripts\python.exe tools/build_application.py
.venv\Scripts\python.exe tools/build_installer.py --without-voice
```

Сборщик приложения запускает тесты и готовит пустой проект без школьной базы, личных шаблонов и голосовой модели. `--with-voice` подключает предварительно подготовленный локальный голосовой пакет. Локальные школьные сборки требуют явного `--private-school` на обоих этапах и не допускаются к публикации.

Не добавляйте в Git базы, полные копии, исходные документы школы, записи голоса, диалоги, ключи или файлы из `build` и `dist`. Новые публичные файлы нужно явно разрешить в закрытом по умолчанию `.gitignore` и проверить перед коммитом.

Порядок выпуска и подписи обновлений описан в [AUTO-UPDATES.md](AUTO-UPDATES.md); правила обращения с данными — в [PRIVACY.md](../PRIVACY.md).
