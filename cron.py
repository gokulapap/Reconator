import os
from time import sleep
import psycopg2
import base64

DATABASE_URL = os.environ['DATABASE_URL']

conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()

#checks the db queue table every 60 secs
while True:
 try:
   cur.execute("select * from queue limit 1")
   t = cur.fetchall()
   t = t[0]
   id = t[0]
   url = t[1]
   conn.commit()
   cur.execute(f"delete from queue where id = '{id}'")
   conn.commit()

   #sends to run.py
   os.system('python run.py {}'.format(url))
   #30 minutes sleep for scan to be finished
   sleep(1740)

 except:
   sleep(60)

cur.close()
conn.close()

