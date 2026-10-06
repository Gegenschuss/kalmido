FROM python:3.12-slim
RUN pip install --no-cache-dir flask==3.1.3 werkzeug==3.1.9 waitress==3.0.2 python-dateutil==2.9.0 cryptography==50.0.1 icalendar==7.3.0 recurring-ical-events==3.8.2 x-wr-timezone==2.0.1 click==8.5.0 segno==1.6.6 webauthn==3.0.1 cbor2==6.1.4 pyasn1==0.6.4 pyasn1-modules==0.4.2 pyOpenSSL==26.4.0 typing-extensions==4.16.0 pillow==12.3.0 tzdata
WORKDIR /app
COPY app.py VERSION /app/
COPY kalmido /app/kalmido
COPY static /app/static
EXPOSE 3040
CMD ["python", "app.py"]
