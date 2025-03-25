# Use Python 3.9 slim image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Create a script to run either webapp or worker
RUN echo '#!/bin/bash\n\
if [ "$1" = "webapp" ]; then\n\
    python webapp.py\n\
elif [ "$1" = "worker" ]; then\n\
    python worker.py\n\
else\n\
    echo "Please specify either webapp or worker"\n\
    exit 1\n\
fi' > /app/start.sh \
&& chmod +x /app/start.sh

# Default command
CMD ["/app/start.sh", "webapp"] 