
# sends test notification
# creates a db table

import os
import sys
import psycopg2
import base64
import telebot

CHAT_ID = os.environ['CHAT_ID']
API_KEY = os.environ['API_KEY']

bot = telebot.TeleBot(API_KEY)

conn = psycopg2.connect(
    host="db",
    database="test_db",
    user="test_user",
    password="test_password"
)

cur = conn.cursor()

# to save the result of recon on target
cur.execute('''

create table output (

domain varchar(30),
result varchar(10485760),
gau varchar(10485760)
);

''')
conn.commit()

# to save targets in queue
cur.execute('''

create table queue (

id SERIAL PRIMARY KEY,
target varchar(50) NOT NULL

);

''')
conn.commit()

bot.send_message(CHAT_ID, "Test Notification from Reconator !")

cur.close()
conn.close()
