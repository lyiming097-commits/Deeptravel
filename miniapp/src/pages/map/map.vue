<template>
  <view class="map-page">
    <view v-if="mapData" class="map-content">
      <view class="map-summary">
        <view>
          <text class="map-title">{{ mapData.title || '地图详情' }}</text>
          <text class="map-caption">{{ mapData.caption || '拖动或双指缩放查看地图' }}</text>
        </view>
        <text class="point-count">{{ mapData.points.length }} 个地点</text>
      </view>

      <map
        class="detail-map"
        :latitude="mapData.latitude"
        :longitude="mapData.longitude"
        :scale="mapData.scale"
        :markers="mapData.markers"
        :polyline="mapData.polyline"
        :enable-scroll="true"
        :enable-zoom="true"
        :enable-rotate="true"
        :show-compass="true"
        :show-scale="true"
      />

      <view class="map-hint">
        <text>可拖动地图、双指缩放，点击标记查看地点名称</text>
      </view>

      <scroll-view class="place-list" scroll-y :show-scrollbar="false">
        <view
          v-for="(point, index) in mapData.points"
          :key="`${point.name || '地点'}-${point.location || index}`"
          class="place-item"
        >
          <text class="place-index">{{ index + 1 }}</text>
          <view class="place-copy">
            <text class="place-name">{{ point.name || `地点 ${index + 1}` }}</text>
            <text v-if="point.address" class="place-address">{{ point.address }}</text>
          </view>
        </view>
      </scroll-view>
    </view>

    <view v-else class="empty-map">
      <text class="empty-icon">⌖</text>
      <text class="empty-title">地图数据已失效</text>
      <text class="empty-caption">请返回对话后重新打开地图</text>
      <button class="back-button" @tap="goBack">返回对话</button>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'

const mapData = ref(null)

onLoad(() => {
  const stored = uni.getStorageSync('deeptravel_map_preview')
  if (!stored || !Array.isArray(stored.points) || !stored.points.length) return
  mapData.value = {
    ...stored,
    markers: Array.isArray(stored.markers) ? stored.markers : [],
    polyline: Array.isArray(stored.polyline) ? stored.polyline : [],
  }
  uni.setNavigationBarTitle({ title: stored.title || '地图详情' })
})

function goBack() {
  uni.navigateBack({
    fail: () => uni.reLaunch({ url: '/pages/home/home' }),
  })
}
</script>

<style scoped>
.map-page { min-height: 100vh; color: #29443e; background: #f3f8f6; }
.map-content { display: flex; height: 100vh; flex-direction: column; }
.map-summary { display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; gap: 20rpx; padding: 22rpx 28rpx 18rpx; background: #fff; }
.map-title, .map-caption { display: block; }
.map-title { color: #214a42; font-size: 32rpx; font-weight: 700; }
.map-caption { margin-top: 5rpx; color: #82958f; font-size: 21rpx; }
.point-count { flex-shrink: 0; padding: 8rpx 14rpx; border-radius: 18rpx; color: #157a6e; background: #eaf6f2; font-size: 21rpx; font-weight: 700; }
.detail-map { width: 100%; height: 58vh; min-height: 600rpx; flex-shrink: 0; }
.map-hint { flex-shrink: 0; padding: 14rpx 28rpx; color: #748a84; background: #eaf3f0; font-size: 21rpx; }
.place-list { min-height: 0; flex: 1; box-sizing: border-box; padding: 10rpx 24rpx calc(24rpx + env(safe-area-inset-bottom)); }
.place-item { display: flex; align-items: center; gap: 16rpx; margin-top: 10rpx; padding: 17rpx 18rpx; border: 1rpx solid #e0ebe8; border-radius: 16rpx; background: #fff; }
.place-index { display: flex; width: 38rpx; height: 38rpx; flex-shrink: 0; align-items: center; justify-content: center; border-radius: 50%; color: #fff; background: #267e73; font-size: 20rpx; font-weight: 700; }
.place-copy { min-width: 0; }
.place-name, .place-address { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.place-name { color: #33534c; font-size: 25rpx; font-weight: 700; }
.place-address { margin-top: 5rpx; color: #8a9b97; font-size: 20rpx; }
.empty-map { display: flex; min-height: 85vh; align-items: center; justify-content: center; flex-direction: column; padding: 60rpx; text-align: center; }
.empty-icon { color: #64a99b; font-size: 88rpx; }
.empty-title { margin-top: 12rpx; color: #35564e; font-size: 31rpx; font-weight: 700; }
.empty-caption { margin-top: 10rpx; color: #899b96; font-size: 23rpx; }
.back-button { width: 260rpx; margin-top: 32rpx; border-radius: 20rpx; color: #fff; background: #157a6e; font-size: 25rpx; }
</style>
