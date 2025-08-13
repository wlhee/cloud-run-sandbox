FROM ubuntu:20.04

# Install gVisor
RUN apt-get update && apt-get install -y curl
RUN apt-get update && apt-get install -y curl wget
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

# Install Python
RUN apt-get install -y python3

# Copy the application files
COPY main.py .
COPY fib.py .

# Expose the server port
EXPOSE 8080

# Start the server
CMD ["python3", "main.py"]
