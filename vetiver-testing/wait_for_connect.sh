timeout 30 bash -c \
    'status=$(curl -s -o /dev/null -w ''%{http_code}'' http://localhost:3939/__ping__); \
    while [[ "$status" != "200" ]]; \
        do sleep 1; \
        echo "retry"; \
        status=$(curl -s -o /dev/null -w ''%{http_code}'' http://localhost:3939/__ping__); \
        done'