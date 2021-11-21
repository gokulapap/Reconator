#urls gather

url=$1

/app/modules/binaries/gau $url | egrep -v '(.pdf|.css|.png|.jpeg|.jpg|.svg|.gif|.wolf)' | tee -a /app/urls
/app/modules/binaries/gospider -t 150 -s http://$url -d 4 | grep "\[url\]" | cut -d " " -f 5 | egrep -v '(.pdf|.css|.png|.jpeg|.jpg|.svg|.gif|.wolf)' | tee -a /app/urls
/app/modules/binaries/hakrawler -plain -url http://$url -depth 4 | egrep -v '(.pdf|.css|.png|.jpeg|.jpg|.svg|.gif|.wolf)' | tee -a /app/urls


cat /app/urls | qsreplace -a | tee /app/final_urls
