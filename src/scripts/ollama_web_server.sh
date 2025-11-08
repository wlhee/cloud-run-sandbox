#!/bin/bash

# This script requires user input ($1) to be the model to pull and serve.
export OLLAMA_HOST=${OLLAMA_HOST:-http://127.0.0.1:11434}
export OLLAMA_MODEL=$1;

# This function will process the user input ($1)
process_input() {
    local input="$1"
    
    # Check if the input is empty or just whitespace
    if [[ -z "$input" ]]; then
        echo "Input detected, but it was empty. Skipping."
        return
    fi
    
    curl $OLLAMA_HOST/api/chat -d "{ \"model\": \"$OLLAMA_MODEL\", \"messages\": [{\"role\": \"user\", \"content\": \"$input\"}], \"stream\": false }"
}

/usr/local/bin/ollama_install.sh;
ollama serve &
# Wait for the server to start
while ! curl -s $OLLAMA_HOST/api/tags > /dev/null; do
    sleep 1
done
ollama pull $OLLAMA_MODEL; 
echo 'model pull completed'; 


# The main infinite loop
echo "### Background Input Listener Started ###"
echo "Type a message and press Enter. The output will appear after a short delay."
echo "Press Ctrl+C to stop the script."
echo "---"

while read -r -p "Input: " USER_INPUT; do
    # Call the processing function with the input and run it in the background
    process_input "$USER_INPUT" & 
done
