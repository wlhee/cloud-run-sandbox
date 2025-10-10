# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install gVisor dependencies
RUN apt-get update && apt-get install -y curl wget sudo iproute2 iptables procps

# Download the pre-release runsc binary
RUN wget https://storage.googleapis.com/wlhe-prereleased-runsc/runsc -O /usr/local/bin/runsc && \
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