url=$1

echo "4) FIREWALL DETECTION" >> /app/results/${url}-output.txt
printf "\n\n" >> /app/results/${url}-output.txt

wafw00f $url | sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,2})?)?[mGK]//g" | grep "Checking" -A 100 | tee -a /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
