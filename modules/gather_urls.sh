#urls gather

url=$1

echo "16) GATHERING ALL URLS" >> /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

/app/modules/binaries/gau $url | egrep -v '(.pdf|.css|.png|.jpeg|.jpg|.svg|.gif|.wolf)' | tee -a /app/urls
/app/modules/binaries/gospider -t 150 -s http://$url -d 4 | grep "\[url\]" | cut -d " " -f 5 | egrep -v '(.pdf|.css|.png|.jpeg|.jpg|.svg|.gif|.wolf)' | tee -a /app/urls
/app/modules/binaries/hakrawler -plain -url http://$url -depth 4 | egrep -v '(.pdf|.css|.png|.jpeg|.jpg|.svg|.gif|.wolf)' | tee -a /app/urls

cat /app/urls | qsreplace -a | tee /app/final_urls

printf "Gathered all urls for the $url successfully !" >> /app/results/$url-output.txt

# goto /gau/{url} to download the gau_urls file

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
