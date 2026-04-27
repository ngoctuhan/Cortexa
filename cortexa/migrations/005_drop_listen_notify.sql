-- Drop trigger that sends pg_notify for 'new_message' since we migrated to Redis Streams
DROP TRIGGER IF EXISTS message_inserted ON messages;
DROP FUNCTION IF EXISTS notify_new_message();
