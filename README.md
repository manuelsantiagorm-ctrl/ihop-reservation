# 🥞 IHOP Reservation System

Sistema de **reservaciones y administración de mesas** para cadenas de restaurantes IHOP y franquicias similares.  
Diseñado para operar **a nivel internacional** (multi-país, multi-zona horaria y multi-sucursal), con un flujo de trabajo optimizado tanto para clientes como para administradores.

---

## 🌎 Características principales

- 🌐 **Multi-país y multi-zona horaria:** manejo preciso de horarios locales y UTC en sucursales internacionales.  
- 🧭 **Integración con Google Maps y Places API:** localización de sucursales, autocompletado y cálculo de distancia “Cerca de mí”.  
- 🪑 **Gestión avanzada de mesas:** visualización del mapa del restaurante, bloqueo de mesas, zonas (interior, terraza, exterior) y posiciones arrastrables.  
- 📅 **Reservas automáticas:** el sistema sugiere horarios y asigna la mejor mesa disponible.  
- 🔐 **Seguridad profesional:** 
  - Protección de vistas staff y admin.
  - Rate limiting y 2FA para personal.
  - HTTPS, HSTS, CSP y backups automáticos.
- 👑 **Panel Chain Owner:** administrador global por cadena o país con control de sucursales, reportes y analíticas.  
- 📈 **Reportes y estadísticas:** visualización de datos de reservas, ocupación y clientes por sucursal o región.  

---

## 🏗️ Arquitectura

- **Framework:** Django 5.x  
- **Base de datos:** PostgreSQL  
- **Frontend:** Bootstrap + JS modular (sin jQuery pesado)  
- **APIs:** Google Maps / Places / TimeZone  
- **Infraestructura prevista:** AWS (EC2 + RDS + S3 + CloudFront)

---

## 📁 Estructura principal

