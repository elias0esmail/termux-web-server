# MyServer

myserver is your own localhost server stack for Android. You can set up Nginx, PHP-FPM, MariaDB, and Redis servers on your Android device using Termux. Termux Web Server is developed for the Termux terminal and lets you host and test your websites locally with HTTPS support, a full CLI manager, and phpMyAdmin integration.
<br/><br/><br/>

<p align="center">
<img src="https://github.com/elias0esmail/termux-web-server/blob/main/Screenshot.jpg"/>
</p>

<br/><br/><br/>

# How to use ?

**CLI Use :**
  ***Example : `myserver start`***
· `myserver start` to start all services (Nginx, PHP-FPM, MariaDB, Redis).
· `myserver stop` to stop all running services.
· `myserver restart` to restart the whole server stack.
· `myserver status` to show the current server status and information.
· `myserver update` to check and install the latest update.
· `myserver uninstall` to completely remove the server stack.

**Manual Use :**
- Type 1 : to start all services.
- Type 2 : to stop all services.
- Type 3 : to restart all services.
- Type 4 : to refresh and re-check server status.
- Type 5 : to check and apply updates.
· Type 6 : to uninstall the server stack.
· Type 7 : to exit and stop the server.

<br/>

## Support :

* **Apache2 server.**
* **nginx web server.**
* **PHP server.**
* **PHP-FPM server.**
* **MariaDB Database server.**
* **Redis server.**
* **phpMyAdmin database manager.**
* **HTTPS / SSL (self-signed).**

<br/>

## MyServer is available for :

* **Android (Termux)**
* **Linux (Termux-like environments)**
  
<br/>

# How to Install MyServer ?

Open the termux app and type following commands.

  1 - pkg update : 
  ```bash
pkg update -y && pkg upgrade -y
  ```
  2 - Installing the required package:
  ```bash
  install -y python git curl
  ```
  3 - Download the repository from github.com:
  ```bash
  git clone https://github.com/elias0esmail/termux-web-server.git
  ```
  4 - Installation
  ```bash
  cd termux-web-server
  ```
  ```bash
  python install_server.py
  ```
**Or install using a single command:**
  ```bash
  pkg update -y && pkg install -y git python && git clone https://github.com/elias0esmail/termux-web-server.git && cd termux-web-server && python3 install_server.py
  ```

<br/>

## Now MyServer is installed successfully.

**Now type `myserver` to open the interactive manager.**
**Or type `myserver start` to start all services directly.**

<br/>

## Server Information :
After starting the server you can access it from your browser using :

* HTTP URL : [http://localhost:8080](http://localhost:8080)
* HTTPS URL : [https://localhost:8443](https://localhost:8443)
* phpMyAdmin : [http://localhost:8080/phpmyadmin](http://localhost:8080/phpmyadmin)
* phpinfo : [http://localhost:8080/phpinfo](http://localhost:8080/phpinfo)

**Web Root Path : `~/storage/shared/htdocs`**

<br/>

## Developer
**Elias Esmail**
* **📱 WhatsApp : [Chat on WhatsAp](https://api.whatsapp.com/send?phone=967771902342)**
* **🔗 GitHub : @elias0esmail**

<br/>

## License:
This project is provided as-is for personal and educational use.

<br/>
<div align="center">

⭐ If you found this project useful, please give it a star on GitHub! ⭐

Made with ❤️ by Elias Esmail

</div>

