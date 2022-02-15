

echo "17) GF PATTERNS" >> /app/results/$url-output.txt
printf "\n\n" >> /app/results/$url-output.txt

url=$1

mkdir /app/gf
for i in $(/app/modules/binaries/gf -list)
do
 /app/modules/binaries/gf $i /app/results/$url-gau.txt | tee /app/gf/$i-$url
 if [ -s /app/gf/$i-$url ]; then
   printf "=============================" >> /app/results/$url-output.txt
   printf "\n\nGF PATTERN : $i \n\n" >> /app/results/$url-output.txt
   printf "=============================\n\n" >> /app/results/$url-output.txt
   cat /app/gf/$i-$url | tee -a /app/results/$url-output.txt
   printf "\n\n" >> /app/results/$url-output.txt
 fi
done

printf "\n\n\n" >> /app/results/$url-output.txt
printf "##########################################################################################\n" >> /app/results/$url-output.txt
printf "##########################################################################################" >> /app/results/$url-output.txt
printf "\n\n\n" >> /app/results/$url-output.txt
