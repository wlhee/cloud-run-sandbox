# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install gVisor dependencies
RUN apt-get update && apt-get install -y curl wget sudo iproute2 iptables procps

# Install gVisor
RUN ( \
      set -e; \
      ARCH=$(uname -m); \
      URL=https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}; \
      wget ${URL}/runsc ${URL}/runsc.sha512 \
           ${URL}/containerd-shim-runsc-v1 ${URL}/containerd-shim-runsc-v1.sha512; \
      sha512sum -c runsc.sha512 \
              -c containerd-shim-runsc-v1.sha512; \
      rm -f *.sha512; \
      chmod a+rx runsc containerd-shim-runsc-v1; \
      mv runsc containerd-shim-runsc-v1 /usr/local/bin; \
    )

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