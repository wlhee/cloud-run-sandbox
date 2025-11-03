# Use an official Python runtime as a parent image
FROM python:3.11-bullseye

# Install gVisor dependencies
RUN apt-get update && apt-get install -y curl wget sudo iproute2 iptables procps

# Download the pre-release runsc binary
RUN wget https://storage.googleapis.com/wlhe-prereleased-runsc/runsc -O /usr/local/bin/runsc && \
    chmod +x /usr/local/bin/runsc

# Download and install dumb-init.
ADD https://github.com/Yelp/dumb-init/releases/download/v1.2.5/dumb-init_1.2.5_x86_64 /usr/local/bin/dumb-init
RUN chmod +x /usr/local/bin/dumb-init

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

# Use dumb-init as the entrypoint. This acts as a lightweight init system (PID 1)
# to ensure that signals are forwarded correctly to the application and that
# orphaned "zombie" processes are properly reaped. This is crucial for ensuring
# clean and reliable shutdowns, especially when gVisor's runsc command
# terminates the sandbox container.
ENTRYPOINT ["/usr/local/bin/dumb-init", "--"]

# Start the server
CMD ["python3", "-u", "main.py"]