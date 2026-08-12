import os
import re
import json
import time
import discord

from typing import Optional
from datetime import timedelta
from collections import defaultdict
from discord.ext import commands, tasks

# =========================
#          НАСТРОЙКИ
# =========================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Префикс только точка: .бан .кик .мьют
PREFIXES = ['.']

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(*PREFIXES),
    intents=intents,
    help_command=None
)

WELCOME_CHANNEL_ID = 1536083742702043216
DEFAULT_ROLE_ID = 1536078371556032609

# Роли, которым разрешены .бан .мьют .кик
STAFF_ROLE_IDS = {
    1536078371593781332,
    1536078371593781338,
    1536078371593781337
}

# Варны
WARN_LIMIT = 3
WARN_TTL_SECONDS = 24 * 60 * 60  # 1 день
AUTO_MUTE_DURATION = timedelta(minutes=15)

# Анти-спам / анти-пинг
SPAM_LIMIT = 5
SPAM_INTERVAL = 8.0
MENTION_LIMIT = 5

DATA_FILE = 'data.json'

FACE = r'`¯\_(ツ)_/¯`'

INVITE_RE = re.compile(
    r'(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9-]+',
    re.IGNORECASE
)

DURATION_REGEX = re.compile(r'(\d+)\s*([а-яА-Яa-zA-Z]+)')

DURATION_UNITS = {
    # секунды
    'сек': 1, 'секунда': 1, 'секунды': 1, 'секунд': 1, 'с': 1,
    'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1, 's': 1,
    # минуты
    'мин': 60, 'минута': 60, 'минуты': 60, 'минут': 60, 'м': 60,
    'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60, 'm': 60,
    # часы
    'час': 3600, 'часа': 3600, 'часов': 3600, 'ч': 3600,
    'hour': 3600, 'hours': 3600, 'h': 3600,
    # дни
    'дн': 86400, 'день': 86400, 'дня': 86400, 'дней': 86400, 'д': 86400,
    'day': 86400, 'days': 86400, 'd': 86400,
    # недели
    'нед': 604800, 'неделя': 604800, 'недели': 604800, 'недель': 604800,
    'w': 604800, 'week': 604800, 'weeks': 604800
}

# =========================
#          ДАННЫЕ
# =========================

def load_data() -> dict:
    default = {
        'left_roles': {},
        'warns': {},
        'unbans': {}
    }

    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            loaded = json.load(f)

        if not isinstance(loaded, dict):
            return default

        for key, value in default.items():
            loaded.setdefault(key, value)

        return loaded

    except FileNotFoundError:
        return default

    except Exception as e:
        print('Не удалось загрузить data.json:', e)
        return default


data = load_data()


def save_data():
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print('Не удалось сохранить data.json:', e)


# =========================
#        ВРЕМЯ / ВАРНЫ
# =========================

def parse_duration(text: Optional[str]) -> Optional[timedelta]:
    """
    Понимает: 2сек, 5мин, 3дн, 1час, 2нед, 5 min, 3 d, 1 день
    Навсегда: 0, навсегда, perm, permanent, бессрочно
    """
    if text is None:
        return None

    text = str(text).strip().lower()

    if not text:
        return None

    if text in {'0', 'навсегда', 'perm', 'permanent', 'бессрочно', 'бессрочка'}:
        return timedelta(seconds=0)

    total = 0
    matched = False

    for value, unit_raw in DURATION_REGEX.findall(text):
        unit = unit_raw.lower()
        multiplier = DURATION_UNITS.get(unit)

        if multiplier is None:
            for key, mult in DURATION_UNITS.items():
                if unit.startswith(key) or key.startswith(unit):
                    multiplier = mult
                    break

        if multiplier:
            total += int(value) * multiplier
            matched = True

    if not matched:
        return None

    return timedelta(seconds=total)


def human_duration(delta: Optional[timedelta]) -> str:
    if not delta or delta.total_seconds() <= 0:
        return 'постоянно'

    total = int(delta.total_seconds())
    parts = []

    weeks, total = divmod(total, 604800)
    days, total = divmod(total, 86400)
    hours, total = divmod(total, 3600)
    minutes, seconds = divmod(total, 60)

    if weeks:
        parts.append(f'{weeks} нед')
    if days:
        parts.append(f'{days} дн')
    if hours:
        parts.append(f'{hours} ч')
    if minutes:
        parts.append(f'{minutes} мин')
    if seconds or not parts:
        parts.append(f'{seconds} сек')

    return ' '.join(parts)


def make_warn_embed(description: str) -> discord.Embed:
    embed = discord.Embed(
        description=description,
        color=discord.Color.red()
    )
    embed.set_author(name='Предупреждение')
    embed.timestamp = discord.utils.utcnow()
    return embed


async def try_dm(user: discord.abc.User, content: str):
    try:
        await user.send(content)
    except Exception:
        pass


# =========================
#         ПРОВЕРКИ
# =========================

def staff_only():
    async def predicate(ctx):
        if ctx.guild is None:
            return False
        return any(role.id in STAFF_ROLE_IDS for role in ctx.author.roles)

    return commands.check(predicate)


def can_moderate(ctx, member: discord.Member):
    if member is None:
        return False, 'участник не найден'

    if member.id == ctx.author.id:
        return False, 'нельзя применить это к себе'

    if member.id == ctx.guild.me.id:
        return False, 'нельзя применить это к самому боту'

    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        return False, 'твоя роль ниже или равна роли участника'

    if member.top_role >= ctx.guild.me.top_role:
        return False, 'роль бота ниже или равна роли участника'

    return True, None


def is_exempt_auto(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild:
        return True
    return any(role.id in STAFF_ROLE_IDS for role in member.roles)


# =========================
#       АВТО-МОДЕРАЦИЯ
# =========================

async def add_warning(member: discord.Member, message: discord.Message, reason: str):
    guild_key = str(message.guild.id)
    user_key = str(member.id)

    warns_by_user = data['warns'].setdefault(guild_key, {})
    warns = warns_by_user.setdefault(user_key, [])

    if not isinstance(warns, list):
        warns = []
        warns_by_user[user_key] = warns

    now = time.time()

    # Удаляем предупреждения старше 1 дня
    warns[:] = [ts for ts in warns if now - ts <= WARN_TTL_SECONDS]

    warns.append(now)
    count = len(warns)
    save_data()

    if count >= WARN_LIMIT:
        try:
            until = discord.utils.utcnow() + AUTO_MUTE_DURATION
            await member.timeout(
                until,
                reason=f'3 предупреждения | последняя причина: {reason}'
            )
        except Exception:
            pass

        # Сбрасываем варны после выдачи мута
        data['warns'][guild_key][user_key] = []
        save_data()

        dm_text = (
            f'на сервере **{message.guild.name}** у тебя накопилось **{WARN_LIMIT}/{WARN_LIMIT}** предупреждений.\n'
            f'за это выдан тайм-аут на **15 минут**.\n'
            f'предупреждения сброшены. максимум: **{WARN_LIMIT}**.'
        )

        await try_dm(member, dm_text)

    else:
        dm_text = (
            f'на сервере **{message.guild.name}** тебе выдано предупреждение.\n'
            f'текущие предупреждения: **{count}/{WARN_LIMIT}**.\n'
            f'максимум: **{WARN_LIMIT}**. при достижении будет тайм-аут на **15 минут**.'
        )

        await try_dm(member, dm_text)


async def handle_invite(message: discord.Message) -> bool:
    if not INVITE_RE.search(message.content):
        return False

    try:
        await message.delete()
    except Exception:
        pass

    description = (
        f'{message.author.mention}, **пжста не кидай ссылки на серваки какие та, '
        f'а кста след нарушение может быть с мутом {FACE} поэтому осторожней**'
    )

    await message.channel.send(embed=make_warn_embed(description))
    await add_warning(message.author, message, 'приглашение на сервер')

    return True


async def handle_mention_spam(message: discord.Message) -> bool:
    if len(message.raw_mentions) < MENTION_LIMIT:
        return False

    try:
        await message.delete()
    except Exception:
        pass

    description = (
        f'{message.author.mention}, **пжста не пингуй так многа, '
        f'а кста след нарушение может быть с мутом {FACE} поэтому осторожней**'
    )

    await message.channel.send(embed=make_warn_embed(description))
    await add_warning(message.author, message, 'массовые пинги')

    return True


spam_tracker = defaultdict(list)
spam_cooldown = {}


async def handle_spam(message: discord.Message) -> bool:
    content_key = message.content.strip().lower()

    if not content_key:
        return False

    key = (message.guild.id, message.author.id, content_key)
    now = time.time()

    # Если недавно уже наказали за этот же спам - просто удаляем повтор
    if key in spam_cooldown and now - spam_cooldown[key] < 10.0:
        try:
            await message.delete()
        except Exception:
            pass
        return True

    times = spam_tracker[key]

    while times and now - times[0] > SPAM_INTERVAL:
        times.pop(0)

    times.append(now)

    if len(times) >= SPAM_LIMIT:
        times.clear()
        spam_cooldown[key] = now

        try:
            await message.channel.purge(
                limit=SPAM_LIMIT + 5,
                check=lambda m: (
                    m.author.id == message.author.id
                    and m.content.strip().lower() == content_key
                    and (discord.utils.utcnow() - m.created_at).total_seconds() <= SPAM_INTERVAL
                )
            )
        except Exception:
            try:
                await message.delete()
            except Exception:
                pass

        description = (
            f'{message.author.mention}, **пжста не спамь, '
            f'а кста след нарушение может быть с мутом {FACE} поэтому осторожней**'
        )

        await message.channel.send(embed=make_warn_embed(description))
        await add_warning(message.author, message, 'спам')

        return True

    return False


# =========================
#        КОМАНДЫ
# =========================

@bot.command(name='ping')
async def ping(ctx):
    start = time.time()
    msg = await ctx.send('Pong!')
    end = time.time()

    rest = round((end - start) * 1000)
    gateway = round(bot.latency * 1000)

    await msg.edit(content=f'Pong! (gateway: {gateway}ms) (rest: {rest}ms)')


@bot.command(name='бан', aliases=['ban'])
@commands.guild_only()
@staff_only()
async def ban_command(
    ctx,
    member: discord.Member,
    duration: Optional[str] = None,
    *,
    reason: Optional[str] = None
):
    ok, error = can_moderate(ctx, member)
    if not ok:
        await ctx.send(error)
        return

    delta = parse_duration(duration)

    # Если срок не распознан - считаем это причиной, а бан постоянным
    if duration is not None and delta is None:
        reason = f'{duration} {reason}'.strip() if reason else duration
        delta = timedelta(seconds=0)

    if delta is None:
        delta = timedelta(seconds=0)

    reason = reason or 'причина не указана'

    guild_key = str(ctx.guild.id)
    user_key = str(member.id)

    if delta.total_seconds() > 0:
        expiry = time.time() + delta.total_seconds()
        data['unbans'].setdefault(guild_key, {})[user_key] = expiry
        save_data()

        dm_text = (
            f'ты забанен(а) на сервере **{ctx.guild.name}** на **{human_duration(delta)}**.\n'
            f'причина: **{reason}**'
        )
    else:
        data['unbans'].get(guild_key, {}).pop(user_key, None)
        save_data()

        dm_text = (
            f'ты забанен(а) на сервере **{ctx.guild.name}** навсегда.\n'
            f'причина: **{reason}**'
        )

    await try_dm(member, dm_text)

    try:
        await member.ban(reason=f'{ctx.author} | {reason}')
    except discord.Forbidden:
        if delta.total_seconds() > 0:
            data['unbans'].get(guild_key, {}).pop(user_key, None)
            save_data()

        await ctx.send('у бота нет прав или роль участника выше роли бота')
        return

    except Exception:
        if delta.total_seconds() > 0:
            data['unbans'].get(guild_key, {}).pop(user_key, None)
            save_data()

        await ctx.send('не получилось забанить участника')
        return

    embed = discord.Embed(
        description=f'✅ {member.mention} забанен(а).',
        color=discord.Color.green()
    )
    embed.add_field(name='срок', value=human_duration(delta), inline=True)
    embed.add_field(name='причина', value=reason, inline=False)

    await ctx.send(embed=embed)


@bot.command(name='кик', aliases=['kick'])
@commands.guild_only()
@staff_only()
async def kick_command(
    ctx,
    member: discord.Member,
    *,
    reason: Optional[str] = None
):
    ok, error = can_moderate(ctx, member)
    if not ok:
        await ctx.send(error)
        return

    reason = reason or 'причина не указана'

    dm_text = (
        f'тебя кикнули с сервера **{ctx.guild.name}**.\n'
        f'причина: **{reason}**'
    )

    await try_dm(member, dm_text)

    try:
        await member.kick(reason=f'{ctx.author} | {reason}')
    except discord.Forbidden:
        await ctx.send('у бота нет прав или роль участника выше роли бота')
        return
    except Exception:
        await ctx.send('не получилось кикнуть участника')
        return

    embed = discord.Embed(
        description=f'✅ {member.mention} кикнут(а).',
        color=discord.Color.green()
    )
    embed.add_field(name='причина', value=reason, inline=False)

    await ctx.send(embed=embed)


@bot.command(name='мьют', aliases=['mute'])
@commands.guild_only()
@staff_only()
async def mute_command(
    ctx,
    member: discord.Member,
    duration: Optional[str] = None,
    *,
    reason: Optional[str] = None
):
    ok, error = can_moderate(ctx, member)
    if not ok:
        await ctx.send(error)
        return

    # Снятие мута
    if duration and str(duration).lower() in {'снять', 'размьют', 'off', 'none'}:
        try:
            await member.timeout(None, reason=f'размьют от {ctx.author}')
            await ctx.send(f'✅ {member.mention} размьючен(а).')
        except Exception:
            await ctx.send('не получилось снять тайм-аут')
        return

    delta = parse_duration(duration)
    note = ''

    # Если срок не распознан - считаем это причиной и ставим мут на 10 минут
    if duration is not None and delta is None:
        reason = f'{duration} {reason}'.strip() if reason else duration
        delta = timedelta(minutes=10)

    if delta is None or delta.total_seconds() <= 0:
        delta = timedelta(minutes=10)

    # Discord timeout максимум 28 дней
    if delta > timedelta(days=28):
        delta = timedelta(days=28)
        note = '\n(в Discord тайм-аут максимум 28 дней, поэтому срок ограничен)'

    reason = reason or 'причина не указана'
    until = discord.utils.utcnow() + delta

    dm_text = (
        f'тебе выдали тайм-аут на сервере **{ctx.guild.name}** на **{human_duration(delta)}**.\n'
        f'причина: **{reason}**'
    )

    await try_dm(member, dm_text)

    try:
        await member.timeout(until, reason=f'{ctx.author} | {reason}')
    except discord.Forbidden:
        await ctx.send('у бота нет прав или роль участника выше роли бота')
        return
    except Exception:
        await ctx.send('не получилось выдать тайм-аут')
        return

    embed = discord.Embed(
        description=f'✅ {member.mention} получил(а) тайм-аут.',
        color=discord.Color.orange()
    )
    embed.add_field(name='срок', value=human_duration(delta), inline=True)
    embed.add_field(name='причина', value=reason + note, inline=False)

    await ctx.send(embed=embed)


@bot.command(name='помощь', aliases=['help'])
async def help_command(ctx):
    embed = discord.Embed(
        title='команды',
        color=discord.Color.blurple()
    )

    embed.add_field(
        name='модерация',
        value=(
            '`.бан @участник 5мин причина`\n'
            '`.бан @участник навсегда причина`\n'
            '`.кик @участник причина`\n'
            '`.мьют @участник 10мин причина`\n'
            '`.мьют @участник снять`'
        ),
        inline=False
    )

    embed.add_field(
        name='примеры сроков',
        value='`2сек`, `5мин`, `3дн`, `1час`, `2нед`, `навсегда`',
        inline=False
    )

    await ctx.send(embed=embed)


# =========================
#        СОБЫТИЯ
# =========================

@tasks.loop(seconds=30)
async def check_unbans():
    now = time.time()
    changed = False

    for guild_key, users in list(data['unbans'].items()):
        try:
            guild_id = int(guild_key)
        except Exception:
            continue

        guild = bot.get_guild(guild_id)

        if guild is None:
            continue

        if not isinstance(users, dict):
            continue

        for user_key, expiry in list(users.items()):
            try:
                expiry = float(expiry)
            except Exception:
                users.pop(user_key, None)
                changed = True
                continue

            if now >= expiry:
                try:
                    await guild.unban(
                        discord.Object(id=int(user_key)),
                        reason='срок бана истёк'
                    )
                except Exception:
                    pass

                users.pop(user_key, None)
                changed = True

    if changed:
        save_data()


@check_unbans.before_loop
async def before_check_unbans():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f'Ботик {bot.user} проснулся! ❤️')

    if not check_unbans.is_running():
        check_unbans.start()


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild

    guild_key = str(guild.id)
    user_key = str(member.id)

    # Достаём сохранённые роли и удаляем их из хранилища
    saved = data['left_roles'].get(guild_key, {}).pop(user_key, None)

    if saved is not None:
        save_data()

    roles_to_add = []

    if saved:
        for role_id in saved:
            try:
                role_id = int(role_id)
            except Exception:
                continue

            role = guild.get_role(role_id)

            if (
                role
                and not role.is_default()
                and not role.managed
                and role < guild.me.top_role
            ):
                roles_to_add.append(role)

    default_role = guild.get_role(DEFAULT_ROLE_ID)

    if default_role and default_role < guild.me.top_role:
        roles_to_add.append(default_role)

    # Убираем дубли
    roles_to_add = list(dict.fromkeys(roles_to_add))

    if roles_to_add:
        try:
            await member.add_roles(
                *roles_to_add,
                reason='роль при входе / восстановление ролей'
            )
        except Exception as e:
            print('Не удалось выдать роли при входе:', e)

    channel = bot.get_channel(WELCOME_CHANNEL_ID)

    if channel:
        await channel.send(
            f'**к нам зашел новый участник! {member.mention}! '
            f'получается, теперь нас {member.guild.member_count} *(включая ботов)*. '
            f'ну шо сказать, классно!**'
        )


@bot.event
async def on_member_remove(member: discord.Member):
    guild_key = str(member.guild.id)
    user_key = str(member.id)

    role_ids = []

    for role in member.roles:
        if role.is_default():
            continue

        if role.managed:
            continue

        if role.id == DEFAULT_ROLE_ID:
            continue

        role_ids.append(role.id)

    data['left_roles'].setdefault(guild_key, {})[user_key] = role_ids
    save_data()

    channel = bot.get_channel(WELCOME_CHANNEL_ID)

    if channel:
        await channel.send(
            f'**у нас вышел участник {member}, оч жаль(( '
            f'но получается, нас теперь {member.guild.member_count} *(включая ботов),* '
            f'что есть то есть!**'
        )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.webhook_id:
        return

    if message.guild is None:
        await bot.process_commands(message)
        return

    is_command = (
        message.content.startswith('.')
        or message.content.startswith(f'<@{bot.user.id}>')
        or message.content.startswith(f'<@!{bot.user.id}>')
    )

    # Модерация/админы освобождаются от авто-модерации
    if is_exempt_auto(message.author):
        if is_command:
            await bot.process_commands(message)
        return

    # Авто-модерация
    if await handle_invite(message):
        return

    if await handle_mention_spam(message):
        return

    if await handle_spam(message):
        return

    if is_command:
        await bot.process_commands(message)


# =========================
#        ОШИБКИ
# =========================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.NoPrivateMessage):
        await ctx.send('эта команда работает только на сервере.')
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            'похоже, ты не указал(а) все аргументы.\n'
            'пример: `.бан @участник 5мин причина`'
        )
        return

    if isinstance(error, commands.MemberNotFound):
        await ctx.send('не нашёл такого участника на сервере.')
        return

    if isinstance(error, commands.CheckFailure):
        await ctx.send('у тебя нет прав для этой команды.')
        return

    if isinstance(error, commands.CommandInvokeError):
        if isinstance(error.original, discord.Forbidden):
            await ctx.send('у бота нет прав или роль бота ниже роли участника.')
            return

    print('Command error:', error)


# =========================
#          ЗАПУСК
# =========================

bot.run(os.environ['TOKEN'])
