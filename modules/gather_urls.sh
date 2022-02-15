
#urls gather

url=$1

echo "16) GATHERING ALL URLS" >> /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

/app/modules/binaries/gau $url | egrep -v '(.pdf|.css|.png|.jpeg|.jpg|.svg|.gif|.wolf)' | tee -a /app/urls
/app/modules/binaries/gospider -t 20 -s http://$url -d 3 | grep "\[url\]" | cut -d " " -f 5 | egrep -v '(.pdf|.css|.png|.jpeg|.jpg|.svg|.gif|.wolf)' | tee -a /app/urls

cat /app/urls | /app/modules/binaries/qsreplace -a | tee /app/results/$url-gau.txt

printf "Gathered all urls for the $url successfully !\n" >> /app/results/$url-output.txt
printf "Goto /gau/{url} to view all the gathered urls | Download the file for your future recon" >> /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
