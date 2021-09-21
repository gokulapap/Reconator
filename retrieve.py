import os
import psycopg2
import base64

DATABASE_URL = os.environ['DATABASE_URL']

conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()

cur.execute("select * from output;")
t = cur.fetchall()

for i in t:
  url = t[0]
  res = t[1]
  os.mkdir('results/{}'.format(url))
  final = base64.standard_b64decode(res)
  final = final.decode('utf-8')
  f = open('results/{}/output.txt'.format(url), 'w')
  f.write(final)
  f.close()

conn.commit()
cur.close()
conn.close()
