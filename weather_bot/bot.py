import os
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from aiogram.types import BotCommand
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from aiogram.filters import CommandObject
from aiogram.types import ContentType
import pytz  # Для работы с часовыми поясами (если потребуется)
import hashlib
import asyncio
from aiogram import F, exceptions

# Инициализация планировщика
scheduler = AsyncIOScheduler()

# Хранилище подписок
subscriptions = {}

# Загрузка переменных окружения
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

# Инициализация бота
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Настройки пользователя
user_preferences = {}

# Установка подписки
@dp.message(Command("subscribe"))
async def subscribe_command(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_preferences or "city" not in user_preferences[user_id]:
        await message.answer(
            "Сначала установите город по умолчанию с помощью команды /setcity."
        )
        return

    await message.answer(
        "Введите время в формате HH:MM (например, 08:00), когда вы хотите получать уведомления о погоде."
    )
    user_preferences[user_id]["awaiting_subscription_time"] = True






@dp.message(lambda message: message.text and message.text.replace(":", "").isdigit())
async def handle_subscription_time(message: types.Message):
    user_id = message.from_user.id
    if user_preferences.get(user_id, {}).get("awaiting_subscription_time"):
        time = message.text
        try:
            # Проверка валидности времени
            datetime.strptime(time, "%H:%M")
        except ValueError:
            await message.answer("Неверный формат времени. Попробуйте еще раз (например, 08:00).")
            return

        city = user_preferences[user_id]["city"]
        subscriptions[user_id] = {"city": city, "time": time}

        # Добавление задачи в планировщик
        hours, minutes = map(int, time.split(":"))
        scheduler.add_job(
            send_weather_update,
            CronTrigger(hour=hours, minute=minutes),
            args=[user_id, city],
            id=str(user_id),  # Уникальный ID задачи
            replace_existing=True  # Заменить задачу, если она уже существует
        )

        user_preferences[user_id].pop("awaiting_subscription_time", None)
        await message.answer(f"Вы подписаны на погоду для города {city} в {time} ежедневно.")
    else:
        await message.answer("Для этой команды требуются другие параметры.")

async def send_weather_update(user_id, city):
    units = user_preferences.get(user_id, {}).get("units", "metric")
    lang = user_preferences.get(user_id, {}).get("lang", "ru")
    weather = get_weather(city, units, lang)
    try:
        await bot.send_message(user_id, f"Ежедневная погода для города {city}:\n{weather}")
    except Exception as e:
        print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")







# Функции для получения погоды и прогноза
def get_weather(city: str, units: str = "metric", lang: str = "ru") -> str:
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": units,
        "lang": lang
    }
    
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        description = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        wind_speed = data["wind"]["speed"]
        wind_direction = data["wind"].get("deg", "нет данных")
        direction = get_wind_direction(wind_direction)
        
        return (
            f"Погода в {city.capitalize()}:\n"
            f"Температура: {temp}°{get_temperature_unit(units)}\n"
            f"Ощущается как: {feels_like}°{get_temperature_unit(units)}\n"
            f"Описание: {description.capitalize()}\n"
            f"Влажность: {humidity}%\n"
            f"Скорость ветра: {wind_speed} м/с, направление: {direction}"
        )
    elif response.status_code == 404:
        return f"Город {city} не найден. Проверьте правильность написания."
    else:
        return f"Ошибка при запросе данных: {response.text}"

def get_forecast(city: str, days: int = 3, units: str = "metric", lang: str = "ru") -> str:
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": units,
        "lang": lang
    }
    
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        forecast_data = data["list"][:days * 8]  # 8 временных отрезков на день
        
        daily_summary = {}
        for item in forecast_data:
            date = item["dt_txt"].split(" ")[0]
            temp = item["main"]["temp"]
            rain = item.get("rain", {}).get("3h", 0)
            wind_speed = item["wind"]["speed"]
            
            if date not in daily_summary:
                daily_summary[date] = {
                    "temps": [],
                    "rain": 0,
                    "wind_speeds": []
                }
            
            daily_summary[date]["temps"].append(temp)
            daily_summary[date]["rain"] += rain
            daily_summary[date]["wind_speeds"].append(wind_speed)
        
        forecast_text = f"Прогноз погоды для {city.capitalize()}:\n"
        for date, summary in daily_summary.items():
            avg_temp = sum(summary["temps"]) / len(summary["temps"])
            avg_wind = sum(summary["wind_speeds"]) / len(summary["wind_speeds"])
            forecast_text += (
                f"{date}:\n"
                f"- Средняя температура: {avg_temp:.1f}°{get_temperature_unit(units)}\n"
                f"- Вероятность осадков: {summary['rain']} мм\n"
                f"- Средняя скорость ветра: {avg_wind:.1f} м/с\n"
            )
        
        return forecast_text
    elif response.status_code == 404:
        return f"Город {city} не найден. Проверьте правильность написания."
    else:
        return f"Ошибка при запросе данных: {response.text}"

def get_wind_direction(deg: int) -> str:
    directions = [
        "северный", "северо-восточный", "восточный", "юго-восточный",
        "южный", "юго-западный", "западный", "северо-западный"
    ]
    idx = round(deg / 45) % 8
    return directions[idx]

def get_temperature_unit(units: str) -> str:
    return "C" if units == "metric" else "F"

# Обработчики команд
@dp.message(Command("start"))
async def start_command(message: types.Message):
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="Получить погоду")],
            [types.KeyboardButton(text="Настройки")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "Добро пожаловать! Выберите команду из меню ниже или используйте кнопки. \nУчтите, прогноз погоды предоставляется в информационных целях. Точность данных зависит от источника",
        reply_markup=keyboard
    )

@dp.message(Command("help"))
async def help_command(message: types.Message):
    await message.answer(
        "Доступные команды:\n"
        "/weather [город] - текущая погода\n"
        "/forecast [город] - прогноз на 3 дня\n"
        "/setcity [город] - установить город по умолчанию\n"
        "/units - сменить единицы измерения\n"
        "/subscribe - подписка на ежедневную погоду"
    )

# Обработка команд без параметров
@dp.message(Command("weather"))
async def weather_command(message: types.Message, command: CommandObject):
    city = command.args or user_preferences.get(message.from_user.id, {}).get("city")
    if not city:
        await message.answer("Пожалуйста, укажите город. Например: /weather Москва")
    else:
        units = user_preferences.get(message.from_user.id, {}).get("units", "metric")
        lang = user_preferences.get(message.from_user.id, {}).get("lang", "ru")
        weather = get_weather(city, units, lang)
        await message.answer(weather)

@dp.message(Command("forecast"))
async def forecast_command(message: types.Message, command: CommandObject):
    city = command.args or user_preferences.get(message.from_user.id, {}).get("city")
    if not city:
        await message.answer("Пожалуйста, укажите город. Например: /forecast Москва")
    else:
        units = user_preferences.get(message.from_user.id, {}).get("units", "metric")
        lang = user_preferences.get(message.from_user.id, {}).get("lang", "ru")
        forecast = get_forecast(city, 3, units, lang)
        await message.answer(forecast)


@dp.message(Command("setcity"))
async def setcity_command(message: types.Message, command: CommandObject):
    city = command.args
    if city:
        user_preferences.setdefault(message.from_user.id, {})["city"] = city
        await message.answer(f"Ваш город установлен: {city}")
    else:
        await message.answer("Пожалуйста, укажите город после команды /setcity. Например: /setcity Москва")

@dp.message(Command("units"))
async def units_command(message: types.Message):
    current_units = user_preferences.setdefault(message.from_user.id, {}).get("units", "metric")
    new_units = "imperial" if current_units == "metric" else "metric"
    user_preferences[message.from_user.id]["units"] = new_units
    await message.answer(f"Единицы измерения изменены на {'Фаренгейт' if new_units == 'imperial' else 'Цельсий'}.")

@dp.inline_query()
async def inline_query_handler(inline_query: InlineQuery):
    city = inline_query.query.strip()
    if not city:
        await inline_query.answer([], cache_time=1)
        return

    weather = get_weather(city)
    result_id = hashlib.md5(city.encode()).hexdigest()
    result = InlineQueryResultArticle(
        id=result_id,
        title=f"Погода в {city}",
        input_message_content=InputTextMessageContent(message_text=weather)
    )
    await inline_query.answer([result], cache_time=1)
# Обработчики для клавиатуры
@dp.message(lambda message: message.text == "Получить погоду")
async def handle_get_weather(message: types.Message):
    await message.answer(
        "Введите /weather [город], чтобы узнать погоду в конкретном городе, "
        "или установите город по умолчанию с помощью команды /setcity [город]."
    )

@dp.message(lambda message: message.text == "Настройки")
async def handle_settings(message: types.Message):
    await message.answer(
        "Настройки:\n"
        "- Установить город по умолчанию: /setcity [город]\n"
        "- Сменить единицы измерения: /units"
    )

@dp.message(F.text.startswith("/") & F.text)
async def unknown_command(message: types.Message):
    # Проверка, зарегистрирована ли команда
    registered_commands = ["/weather", "/forecast", "/setcity", "/units", "/subscribe", "/help"]
    if message.text.split()[0] not in registered_commands:
        await message.answer(
            "Неизвестная команда. Используйте /help для получения списка доступных команд."
        )



# Пример использования списка команд (в настройке меню)
async def set_bot_commands(bot: Bot):
    commands = [
        types.BotCommand(command="/help", description="Справка о командах"),
        types.BotCommand(command="/weather", description="Текущая погода"),
        types.BotCommand(command="/forecast", description="Прогноз погоды на 3 дня"),
        types.BotCommand(command="/setcity", description="Установить город по умолчанию"),
        types.BotCommand(command="/units", description="Сменить единицы измерения"),
        types.BotCommand(command="/subscribe", description="Подписка на ежедневную погоду"),
        
    ]
    await bot.set_my_commands(commands)

# Запуск планировщика в главной функции
async def main():
    scheduler.start()  # Запуск планировщика
    await set_bot_commands(bot)  # Установить команды в Telegram
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

