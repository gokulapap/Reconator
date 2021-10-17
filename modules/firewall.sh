url=$1

echo "6) FIREWALL DETECTION" >> /app/results/${url}-output.txt
printf "\n\n" >> /app/results/${url}-output.txt

wafw00f $url | grep "Checking" -A 100 | tee -a /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "######################################################################" >> /app/results/$url-output.txt
printf "######################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
