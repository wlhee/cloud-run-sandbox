# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install gVisor dependencies
RUN apt-get update && apt-get install -y curl wget sudo iproute2 iptables procps

# Install Google Cloud SDK to access GCS
RUN apt-get install -y apt-transport-https ca-certificates gnupg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key --keyring /usr/share/keyrings/cloud.google.gpg add - && \
    apt-get update && apt-get install -y google-cloud-sdk

# Download the pre-release runsc binary
RUN gcloud storage cp gs://wlhe-prereleased-runsc/runsc /usr/local/bin/runsc && \
    chmod +x /usr/local/bin/runsc

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application files
COPY main.py .
COPY src/ ./src/

# Expose the server port
EXPOSE 8080

# Start the server
CMD ["python3", "-u", "main.py"]