timeout 5 bash -c \
    'status=$(curl -s -o /dev/null -w ''%{http_code}'' http://localhdost:3939/__ping__); \
    while [[ "$status" != "200" ]]; \
        do sleep 1; \
        echo "retry"; \
        status=$(curl -s -o /dev/null -w ''%{http_code}'' http://locadlhost:3939/__ping__); \
        done'