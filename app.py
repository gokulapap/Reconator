from flask import Flask, render_template, send_file, request, redirect, url_for
import os
import psycopg2
import base64

app = Flask(__name__)

conn = psycopg2.connect(
    host="db",
    database="test_db",
    user="test_user",
    password="test_password"
)

cur = conn.cursor()

#########################################################################

@app.route("/")
def home():
  try:
    os.system('python initialise.py')
    return render_template("index.html")
  except:
    return render_template("index.html")

#########################################################################

@app.route("/adder", methods=["GET", "POST"])
def adder():
 if request.method == "POST":
  url = request.form.get('url')
  if url == "":
    return render_template("index.html", info="Cant add empty targets !")
	  
  cur.execute(f"insert into queue (target) values ('{url}')")
  conn.commit()

  return render_template("index.html", info="Added to queue !")

#########################################################################

@app.route("/queue")
def check_queue():
  q1 = r'''
<html>
<head>

<meta charset="utf-8">
    <link href="//maxcdn.bootstrapcdn.com/font-awesome/4.2.0/css/font-awesome.min.css" rel="stylesheet">
    <link rel="stylesheet" href="style.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.2/css/all.min.css"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@200;300;400;500;600;700&display=swap');
*{
  margin: 0;
  padding: 0;
  box-sizing: border-box;
  font-family: 'Poppins', sans-serif;
}

.ul2 {
width:70%;
}

nav{
  z-index: 1;
  position:absolute;
  margin-top: -20px;
  margin-left:-20px;
  display: flex;
  height: 70px;
  width: 100%;
  background: #1b1b1b;
  align-items: center;
  justify-content: space-between;
  padding: 0 50px 0 80px;
}
nav .logo{
  color: #fff;
  font-size: 35px;
  font-weight: 600;
}
nav ul{
  display: flex;
  flex-wrap: wrap;
  list-style: none;
}
nav ul li{
  margin: 0 -15px;
}
nav ul li a{
  color: #f2f2f2;
  text-decoration: none;
  font-size: 18px;
  font-weight: 500;
  padding: 2px 12px;
  border-radius: 5px;
  letter-spacing: 1px;
  transition: all 0.3s ease;
}
nav ul li a.active,
nav ul li a:hover{
  color: #111;
  background: #fff;
}
nav .menu-btn i{
  color: #fff;
  font-size: 20px;
  cursor: pointer;
  display: none;
}
input[type="checkbox"]{
  display: none;
}

@media (max-width: 1000px){
  nav{
    padding: 0 40px 0 40px;
  }

  .ul2 {
   width: 98%;
 }

}

@media (max-width: 920px) {

li {
  color:#fff;
  list-style:none;
  position: relative;
  padding-left:40px;
  line-height: 2;
  font-size:15px;
  display:flex;
  flex-direction:row;
}

li:before {
  font-family:FontAwesome;
  position: absolute;
  left: 0;
  color:#318ca0;
  font-size:15px;

}

li.one:before {
   content:"\f111";
}
li.two:before {
   content:"\f00c";
}
li.three:before {
   content:"\f10c";
}
li.four:before {
   content:"\f004";
}
li.five:before {
   content:"\f1e2";
}
li.six:before {
   content:"\f0e7";
}

li:hover:before {
  color:#fff;
}

 .ul2 {
   width: 98%;
 }

  nav .menu-btn i{
    display: block;
  }
  #click:checked ~ .menu-btn i:before{
    content: "\f00d";
  }

  nav ul{
    position: fixed;
    top: 80px;
    left: -100%;
    background: #111;
    height: 100vh;
    width: 100%;
    text-align: center;
    display: block;
    transition: all 0.3s ease;
  }
  #click:checked ~ ul{
    left: 0;
  }
  nav ul li{
    width: 100%;
    margin: 40px 0;
  }
  nav ul li a{
    width: 100%;
    margin-left: -100%;
    display: block;
    font-size: 20px;
    transition: 0.6s cubic-bezier(0.68, -0.55, 0.265, 1.55);
  }
  #click:checked ~ ul li a{
    margin-left: 0px;
  }
  nav ul li a.active,
  nav ul li a:hover{
    background: none;
    color: cyan;
  }
}
.content{
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  z-index: -1;
  width: 100%;
  padding: 0 30px;
  color: #1b1b1b;
}
.content div{
  font-size: 40px;
  font-weight: 700;
}




button {
  flex:0.2;
  background: #61dafb;
  color: #282c34;
  font-family: "Work Sans", sans-serif;
  font-size: 0.8em;
  margin:none;
  padding: .60em 4em;
  text-align: center;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  -webkit-transition: all 0.2s ease-in-out;
  -ms-transition: all 0.2s ease-in-out;
  transition: all 0.2s ease-in-out;
}
  button.btn-delete {
    /* margin: 0 0 0 10px; */
    padding: 0;
    background: none;
    color: rgba(255, 255, 255, 0.5);
    font-size: 20px;
    font-weight: 200;
    line-height: 1;
    flex-basis: 10%; }

button.btn-delete:hover {
    color: #c92d2d; 
}


* {
  font-family:sans-serif;
  margin: 0;
  padding: 0;
}

body {
  background:#282c34;
  padding:20px;
}

h1 {
  color:#fff;
  font-size: 30px;
}
li {
  color:#fff;
  list-style:none;
  position: relative;
  padding-left:40px;
  line-height: 2;
  font-size:15px;
  display:flex;
  flex-direction:row;
}
.urlname{
  width:70%;
  display: flex;
  align-items: center;
  font-size:15px;
  /* justify-content: center; */
}


li:before {
  font-family:FontAwesome;
  position: absolute;
  left: 0;
  color:#318ca0;
  font-size:15px;

}

li.one:before {
   content:"\f111"; 
}
li.two:before {
   content:"\f00c";
}
li.three:before {
   content:"\f10c";
}
li.four:before {
   content:"\f004";
}
li.five:before {
   content:"\f1e2";
}
li.six:before {
   content:"\f0e7";
}

li:hover:before {
  color:#fff;
}

ul {
font-size:10px;
}


</style>
</head>

<body>

    <nav>
      <div class="logo">Reconator</div>
      <input type="checkbox" id="click">
      <label for="click" class="menu-btn">
        <i class="fas fa-bars"></i>
      </label>
      <ul>
        <li><a href="/">Home</a></li>
        <li><a href="#">About</a></li>
        <li><a class="active" href="#">Queue</a></li>
        <li><a href="scanned">Scanned</a></li>
        <li><a href="issues">Issues</a></li>
      </ul>
    </nav>

<br><br><br><br><br>
<h1 style="text-align:left;"> Targets in Queue </h1>
<br><br>

  <ul class="ul2">
'''

  q2 = '''
	</ul>
	</body>
	</html>
  '''

  res = ''
  res = res + q1

  cur.execute("select * from queue")
  t = cur.fetchall()

  for i in t:
    res = res + '''
    <li class="three">
      <div class=urlname> {} </div>
      <div class="comp">
       <form action="delete" method="POST"><input type="hidden" name="{}"><button class="butn" type="submit">Delete</button></form>
      </div>
    </li>
    '''.format(i[1], i[0])

  res = res + q2
  conn.commit()

  return res

#########################################################################

@app.route("/scanned")
def scanned():
  s1 = r'''
<html>
<head>

<meta charset="utf-8">
    <link href="//maxcdn.bootstrapcdn.com/font-awesome/4.2.0/css/font-awesome.min.css" rel="stylesheet">
    <link rel="stylesheet" href="style.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.2/css/all.min.css"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@200;300;400;500;600;700&display=swap');
*{
  margin: 0;
  padding: 0;
  box-sizing: border-box;
  font-family: 'Poppins', sans-serif;
} 

.ul2 {
width:70%;
}

nav{
  z-index: 1;
  position:absolute;
  margin-top: -20px;
  margin-left:-20px;
  display: flex;
  height: 70px;
  width: 100%;
  background: #1b1b1b;
  align-items: center;
  justify-content: space-between;
  padding: 0 50px 0 80px;
}
nav .logo{
  color: #fff;
  font-size: 35px;
  font-weight: 600;
}
nav ul{
  display: flex;
  flex-wrap: wrap;
  list-style: none;
}
nav ul li{
  margin: 0 -15px;
}
nav ul li a{
  color: #f2f2f2;
  text-decoration: none;
  font-size: 18px;
  font-weight: 500;
  padding: 2px 12px;
  border-radius: 5px;
  letter-spacing: 1px;
  transition: all 0.3s ease;
}
nav ul li a.active,
nav ul li a:hover{
  color: #111;
  background: #fff;
}
nav .menu-btn i{
  color: #fff;
scanned#  font-size: 20px;
  cursor: pointer;
  display: none;
}
input[tyscanned#pe="checkbox"]{
  display: none;
}

@media (max-width: 1000px){
  nav{
    padding: 0 40px 0 40px;
  }

  .ul2 {
   width: 98%;
 }

}

@media (max-width: 920px) {

li {
  color:#fff;
  list-style:none;
  position: relative;
  padding-left:40px;
  line-height: 2;
  font-size:15px;
  display:flex;
  flex-direction:row;
}

li:before {
  font-family:FontAwesome;
  position: absolute;
  left: 0;
  color:#318ca0;
  font-size:15px;

}

li.one:before {
   content:"\f111";
}
li.two:before {
   content:"\f00c";
}
li.three:before {
   content:"\f10c";
}
li.four:before {
   content:"\f004";
}
li.five:before {
   content:"\f1e2";
}
li.six:before {
   content:"\f0e7";
}

li:hover:before {
  color:#fff;
}

 .ul2 {
   width: 98%;
 }

  nav .menu-btn i{
    display: block;
  }
  #click:checked ~ .menu-btn i:before{
    content: "\f00d";
  }

  nav ul{
    position: fixed;
    top: 80px;
    left: -100%;
    background: #111;
    height: 100vh;
    width: 100%;
    text-align: center;
    display: block;
    transition: all 0.3s ease;
  }
  #click:checked ~ ul{
    left: 0;
  }
  nav ul li{
    width: 100%;
    margin: 40px 0;
  }
  nav ul li a{
    width: 100%;
    margin-left: -100%;
    display: block;
    font-size: 20px;
    transition: 0.6s cubic-bezier(0.68, -0.55, 0.265, 1.55);
  }
  #click:checked ~ ul li a{
    margin-left: 0px;
  }
  nav ul li a.active,
  nav ul li a:hover{
    background: none;
    color: cyan;
  }
}
.content{
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  z-index: -1;
  width: 100%;
  padding: 0 30px;
  color: #1b1b1b;
}
.content div{
  font-size: 40px;
  font-weight: 700;
}


button {
  flex:0.2;
  background: #61dafb;
  color: #282c34;
  font-family: "Work Sans", sans-serif;
  font-size: 0.8em;
  margin:none;
  padding: .60em 4em;
  text-align: center;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  -webkit-transition: all 0.2s ease-in-out;
  -ms-transition: all 0.2s ease-in-out;
  transition: all 0.2s ease-in-out;
}
  button.btn-delete {
    /* margin: 0 0 0 10px; */
    padding: 0;
    background: none;
    color: rgba(255, 255, 255, 0.5);
    font-size: 20px;
    font-weight: 200;
    line-height: 1;
    flex-basis: 10%; }

button.btn-delete:hover {
    color: #c92d2d; 
}




* {
  font-family:sans-serif;  
  margin: 0;
  padding: 0;
}

body {
  background:#282c34;
  padding:20px;
}

h1 {
  color:#fff;
  font-size: 30px;
}
li {
  color:#fff;
  list-style:none;
  position: relative;
  padding-left:40px;
  line-height: 2;
  font-size:15px;
  display:flex;
  flex-direction:row;
}
.urlname{
  width:70%;
  display: flex;
  align-items: center;
  font-size:15px;
  /* justify-content: center; */
}


li:before {
  font-family:FontAwesome;
  position: absolute;
  left: 0;
  color:#318ca0;
  font-size:15px;

}

li.one:before {
   content:"\f111"; 
}
li.two:before {
   content:"\f00c";
}
li.three:before {
   content:"\f10c";
}
li.four:before {
   content:"\f004";
}
li.five:before {
   content:"\f1e2";
}
li.six:before {
   content:"\f0e7";
}

li:hover:before {
  color:#fff;
}

ul {
font-size:10px;
}


</style>
</head>

<body>

    <nav>
      <div class="logo">Reconator</div>
      <label for="click" class="menu-btn">
        <i class="fas fa-bars"></i>
      </label>
      <ul>
        <li><a href="/">Home</a></li>
        <li><a href="#">About</a></li>
        <li><a href="queue">Queue</a></li>
        <li><a class="active" href="#">Scanned</a></li>
        <li><a href="issues">Issues</a></li>
      </ul>
    </nav>

<br><br><br><br><br>
<h1 style="text-align:left;"> Scanned Targets </h1>
<br><br>

  <ul class="ul2">
'''
  s2 = '''
 </ul>
 </body>
 </html>
 '''
  res = ''
  res = res + s1

  cur.execute("select domain from output")
  t = cur.fetchall()

  for i in t:
    res = res + '''
    <li class="two">
      <div class=urlname>{}</div>
      <div class="comp">
       <a href="/output/{}"><button class="butn" type="submit">Report</button></a>
      </div>
    </li>
   '''.format(i[0] ,i[0])

  res = res + s2
  conn.commit()
  return res

#########################################################################

@app.route("/delete", methods=["POST"])
def delete_item():
  t = request.form
  dic = dict(t)
  key = list(dic.keys())
  id = key[0]

  cur.execute("delete from queue where id={}".format(id))
  conn.commit()

  return redirect(url_for("check_queue"))

#########################################################################

@app.route("/issues")
def issues():
  return render_template("issues.html")

#########################################################################

@app.route("/about")
def about():
  return redirect("https://github.com/gokulapap/Reconator/wiki")

#########################################################################

@app.route("/output/<url>")
def output(url):
  url = url

  cur.execute(f"select result from output where domain = '{url}'")
  t = cur.fetchall()

  res = t[0][0]
  final = base64.standard_b64decode(res)
  final = final.decode('utf-8')
  os.system(f"touch /app/results/{url}-output.txt")
  f = open('/app/results/{}-output.txt'.format(url), 'w')
  f.write(final)
  f.close()

  conn.commit()

  return send_file("/app/results/{}-output.txt".format(url))

#########################################################################

@app.route("/initialise")
def initialise():
  try:
    os.system('python initialise.py')
    return "<h2>Initialised sucessfully ! test notification sent to your telegram \/ </h2>"
  except:
    return "<h2> Initialised Already Go to Home page !! </h2>"

#########################################################################

@app.route("/results")
def results():
   return "Results Here!"

#########################################################################

@app.route("/gau/<url>")
def gau_urls(url):
  url = url

  cur.execute(f"select gau from output where domain = '{url}'")
  t = cur.fetchall()

  res = t[0][0]
  final = base64.standard_b64decode(res)
  final = final.decode('utf-8')
  os.system(f"touch /app/results/{url}-gau.txt")
  f = open('/app/results/{}-gau.txt'.format(url), 'w')
  f.write(final)
  f.close()

  conn.commit()

  return send_file("/app/results/{}-gau.txt".format(url))

#########################################################################

if __name__ == "__main__":
  app.run(host='0.0.0.0', port=5000)

