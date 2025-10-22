import WebSocket from 'ws';
import { EventEmitter } from 'events';

/**
 * A callback function that determines whether the connection should attempt to reconnect.
 * @param code The WebSocket closing status code.
 * @param reason A Buffer containing the reason for closing.
 * @returns `true` if a reconnection should be attempted, `false` otherwise.
 */
export type ShouldReconnectCallback = (code: number, reason: Buffer) => boolean;

export type ReconnectInfo = {
  url: string;
  wsOptions?: WebSocket.ClientOptions;
};

export type GetReconnectInfoCallback = () => ReconnectInfo;


/**
 * A WebSocket connection wrapper that provides automatic reconnection capabilities.
 * It emits standard WebSocket events (`open`, `message`, `close`, `error`) and an additional `reopen` event
 * when it's about to attempt a reconnection.
 */
export class Connection extends EventEmitter {
  private ws: WebSocket | null = null;
  private url: string;
  private wsOptions?: WebSocket.ClientOptions;
  private shouldReconnect: ShouldReconnectCallback;
  private getReconnectInfo: GetReconnectInfoCallback;
  private isReconnecting: boolean = false;

  /**
   * A flag to indicate if the connection was closed intentionally by the user calling `close()`.
   * If `true`, no reconnection attempts will be made.
   */
  private isClosedIntentionally: boolean = false;

  /**
   * Creates an instance of the Connection class.
   * @param url The URL to connect to.
   * @param shouldReconnect A callback that is invoked when the connection closes to determine if a reconnect should be attempted.
   * @param getReconnectInfo A callback that returns the URL and options for reconnection.
   * @param wsOptions Optional client options for the underlying `ws` WebSocket instance.
   */
  constructor(
    url: string,
    shouldReconnect: ShouldReconnectCallback,
    getReconnectInfo: GetReconnectInfoCallback,
    wsOptions?: WebSocket.ClientOptions,
  ) {
    super();
    this.url = url;
    this.shouldReconnect = shouldReconnect;
    this.getReconnectInfo = getReconnectInfo;
    this.wsOptions = wsOptions;
    this.connect();
  }

  /**
   * Establishes the WebSocket connection and sets up event listeners.
   * This method is called initially and for every reconnection attempt.
   */
  private connect() {
    this.ws = new WebSocket(this.url, this.wsOptions);

    this.ws.on('open', () => {
      if (this.isReconnecting) {
        this.isReconnecting = false;
        this.emit('reopen');
      } else {
        this.emit('open');
      }
    });

    /**
     * Emitted when a message is received from the server.
     * @event message
     * @param {WebSocket.Data} data The received data.
     */
    this.ws.on('message', (data) => {
      this.emit('message', data);
    });

    /**
     * Handles the closing of the connection.
     * If the close was not intentional, it consults the `shouldReconnect` callback.
     */
    this.ws.on('close', (code, reason) => {
      // If the connection was closed intentionally, do not reconnect.
      if (this.isClosedIntentionally) {
        /**
         * Emitted when the connection has been closed.
         * @event close
         * @param {number} code The closing status code.
         * @param {Buffer} reason The reason for closing.
         */
        this.emit('close', code, reason);
        return;
      }

      // Ask the user if we should reconnect.
      if (this.shouldReconnect(code, reason)) {
        this.isReconnecting = true;
        const reconnectInfo = this.getReconnectInfo();
        this.url = reconnectInfo.url;
        this.wsOptions = reconnectInfo.wsOptions || this.wsOptions;
        this.connect();
      } else {
        this.emit('close', code, reason);
      }
    });

    /**
     * Emitted when an error occurs on the connection.
     * @event error
     * @param {Error} err The error object.
     */
    this.ws.on('error', (err) => {
      this.emit('error', err);
    });
  }

  /**
   * Sends data over the WebSocket connection.
   * @param data The data to send.
   */
  public send(data: string | Buffer | ArrayBuffer | Buffer[]) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    } else {
      this.emit('error', new Error('WebSocket is not open. Cannot send data.'));
    }
  }

  /**
   * Closes the WebSocket connection intentionally.
   * Once this is called, no reconnection attempts will be made.
   * @param code The status code for closing.
   * @param reason The reason for closing.
   */
  public close(code?: number, reason?: string) {
    this.isClosedIntentionally = true;
    if (this.ws) {
      this.ws.close(code, reason);
    }
  }
}
