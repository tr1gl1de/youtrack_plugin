# YouTrack plugin for Claude Code

[English](#english) · [Русский](#русский)

---

## English

A [Claude Code](https://claude.com/claude-code) plugin that lets Claude work with
[JetBrains YouTrack](https://www.jetbrains.com/youtrack/) over the REST API: read and search issues,
create and update them, change fields with YouTrack commands, comment, log time, and read or edit
Knowledge Base articles.

It ships one skill, `youtrack`, plus a dependency-free Python 3 CLI (`skills/youtrack/scripts/yt.py`).
Claude loads the skill on its own when you mention an issue ID such as `KIN-12` or a YouTrack link.

### Install

```text
/plugin marketplace add tr1gl1de/youtrack_plugin
/plugin install youtrack@youtrack-plugin
```

Requirements: Python 3.9+ and `git` on `PATH`.

### Configure

Create a permanent token in YouTrack (**Profile → Account Security → Tokens**, scope *YouTrack*), then
put the settings in **one** of these places. Each key is looked up separately, first match wins:

1. Environment variables.
2. `.env` in the root of the repository you are working in, for per-project settings.
3. `~/.config/youtrack/.env`, shared by all repositories.

```dotenv
YOUTRACK_URL=https://your-instance.youtrack.cloud
YOUTRACK_TOKEN=perm:...
YOUTRACK_PROJECT=KIN   # optional default project
```

Remember to add `.env` to the repository's `.gitignore`. Check the result with:

```bash
python3 ~/.claude/plugins/.../skills/youtrack/scripts/yt.py config   # token is never printed
```

### Usage

Just ask Claude:

- "Take KIN-12 and summarize what needs to be done"
- "What's assigned to me and unresolved?"
- "Move KIN-12 to Review and comment with the PR link"
- "Read the Git Flow article in the knowledge base"

Claude reads freely. It writes to YouTrack (comments, field changes, time, articles) only when you ask
it to. The plugin has no delete command.

### CLI reference

```bash
yt.py config | whoami | projects | fields [PROJECT]
yt.py issue get ID [--comments]
yt.py issue search "QUERY" [-p PROJECT | -A] [-n N]
yt.py issue create -s SUMMARY [-d TEXT|-|@file] [--command "Type Bug"]
yt.py issue update ID [-s SUMMARY] [-d TEXT|-|@file]
yt.py issue command "COMMAND" ID [ID...] [--comment TEXT]
yt.py comment list ID | comment add ID TEXT|-|@file
yt.py article get ID | article search "QUERY" | article update ID [--content TEXT|-|@file]
yt.py time list ID | time add ID 1h30m [-t TEXT] [--type TYPE]
yt.py api METHOD PATH [-P key=value] [-D JSON|-|@file]
yt.py --json ...   # raw JSON output
```

---

## Русский

Плагин для [Claude Code](https://claude.com/claude-code). Он даёт Claude доступ к
[JetBrains YouTrack](https://www.jetbrains.com/youtrack/) через REST API. Claude сможет читать и искать
задачи, создавать и обновлять их, менять поля командами YouTrack, писать комментарии, учитывать время,
а также читать и редактировать статьи базы знаний.

В плагине один skill `youtrack` и CLI на Python 3 без зависимостей (`skills/youtrack/scripts/yt.py`).
Claude подключает skill сам, когда вы упоминаете ID задачи вроде `KIN-12` или ссылку на YouTrack.

### Установка

```text
/plugin marketplace add tr1gl1de/youtrack_plugin
/plugin install youtrack@youtrack-plugin
```

Нужны Python 3.9+ и `git` в `PATH`.

### Настройка

Создайте постоянный токен в YouTrack (**Профиль → Account Security → Tokens**, scope *YouTrack*).
Затем укажите настройки в **одном** из мест ниже. Каждый ключ ищется отдельно, побеждает первое совпадение:

1. Переменные окружения.
2. `.env` в корне текущего репозитория, если настройки нужны для одного проекта.
3. `~/.config/youtrack/.env`, общий для всех репозиториев.

```dotenv
YOUTRACK_URL=https://your-instance.youtrack.cloud
YOUTRACK_TOKEN=perm:...
YOUTRACK_PROJECT=KIN   # необязательно: проект по умолчанию
```

Не забудьте добавить `.env` в `.gitignore` репозитория. Проверить настройки можно командой
`yt.py config`; токен она не выводит.

### Использование

Просто попросите Claude:

- «Возьми KIN-12 и опиши, что нужно сделать»
- «Какие нерешённые задачи на мне?»
- «Переведи KIN-12 в Review и оставь комментарий со ссылкой на PR»
- «Прочитай статью про Git Flow в базе знаний»

Читать Claude может свободно. В YouTrack он пишет (комментарии, поля, время, статьи) только по вашей
просьбе. Команды удаления в плагине нет.

## License

MIT, see [LICENSE](LICENSE).
