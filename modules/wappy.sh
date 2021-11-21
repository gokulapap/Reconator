#!/bin/bash

url=$1

echo "15) WEB TECHNOLOGIES" >> /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

python /app/modules/binaries/wappy -u $url | tee -a /app/results/$url-output.txt

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
