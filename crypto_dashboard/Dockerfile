# Use an official Python runtime as the base image
FROM python:3.10-slim

# Set working directory in the container
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all your Python files
COPY app.py .
COPY calculations.py .
COPY CategoryRank.py .
COPY MCrolling.py .
COPY strength.py .
COPY tokenstrength.py .

# Run all scripts using supervisor
RUN apt-get update && apt-get install -y supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Command to run supervisor
CMD ["/usr/bin/supervisord"] 