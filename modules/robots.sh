#!/bin/bash

#robots.txt checker

url=$1

echo "6) ROBOTS.TXT CHECKER" >> /app/results/${url}-output.txt
printf "\n\n" >> /app/results/${url}-output.txt

python /app/modules/binaries/robots $url | tee -a /app/results/${url}-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
