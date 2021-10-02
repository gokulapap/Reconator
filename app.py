from flask import Flask, render_template, send_file, request
from bp import auto_bp
import os
import psycopg2

app = Flask(__name__)
app.register_blueprint(auto_bp, url_prefix='/results')

@app.route("/")
def home():
   return render_template("index.html")

@app.route("/adder", methods=["GET", "POST"])
def adder():
 if request.method == "POST":
  url = request.form.get('url')
  DATABASE_URL = os.environ['DATABASE_URL']

  conn = psycopg2.connect(DATABASE_URL, sslmode='require')
  cur = conn.cursor()

  cur.execute(f"insert into queue ('target',) values ('{url}')")
  conn.commit()

  cur.close()
  conn.close()

  return render_template("index.html", data="Added to queue !")

@app.route("/queue")
def check_queue():
  str = '<h1>Targets in queue are</h1><br><ul>'
  DATABASE_URL = os.environ['DATABASE_URL']
  conn = psycopg2.connect(DATABASE_URL, sslmode='require')
  cur = conn.cursor()
  cur.execute("select * from queue")
  t = cur.fetchall()
  for i in t:
    str = str + '<li> {}'.format(i[1])
  str = str + "</ul>"
  conn.commit()
  cur.close()
  conn.close()

  return str

@app.route("/scanned")
def scanned():
  str = '<h1>Scanned Targets are</h1><br><ul>'
  DATABASE_URL = os.environ['DATABASE_URL']
  conn = psycopg2.connect(DATABASE_URL, sslmode='require')
  cur = conn.cursor()
  cur.execute("select domain from output")
  t = cur.fetchall()
  for i in t:
    str = str + f"<li> <a href='/output/{}'>{}</a>".format(i[0], i[0])
  str = str + "</ul>"
  conn.commit()
  cur.close()
  conn.close()

@app.route("/output/<url>")
def output():
  url = url
  os.system(f"python retrieve.py {url}")
  return send_file("/app/results/{}-output.txt".format(url))

@app.route("/initialise")
def initialise():
  os.system('python initialise.py')
  return 'Initialised sucessfully ! test notification sent \/'

@app.route("/results")
def results():
   return "Results Here!"

if __name__ == "__main__":
  app.run(port=8000)
