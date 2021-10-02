# python insert.py {domain}

import os
import sys
import psycopg2
import base64
import telebot

bot = telebot.TeleBot(os.environ['API_KEY'])
chat_id = os.environ['CHAT_ID']

url = sys.argv[1]
DATABASE_URL = os.environ['DATABASE_URL']

conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()

#checking if any previous entry in the database to avoid duplicates

cur.execute("select * from output;")
t = cur.fetchall()

doms = []

for i in t:
  doms.append(i[0])

if url in doms:
  pass

else:
  #read from output.txt and dump in database
  f = open('results/{}-output.txt'.format(url), 'r')
  res = f.read()
  f.close()

  res = bytes(res, 'utf-8')
  final = base64.standard_b64encode(res)
  final = final.decode('utf-8')

  cur.execute(f"insert into output values ('{url}', '{final}');")
  conn.commit()

conn.commit()

bot.send_message(chat_id, f"scanned results of {url} is saved in db")
cur.close()
conn.close()
